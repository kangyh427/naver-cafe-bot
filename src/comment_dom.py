# ============================================================
# 파일명: comment_dom.py
# 경로:   kangyh427/naver-cafe-bot/src/comment_dom.py
# 역할:   네이버 카페 게시글 DOM 접근 전담
#         (게시글 읽기 / 댓글 입력 및 제출)
#
# 작성일: 2026-03-11
# 수정일: 2026-03-13
# 버전:   v5.2
#
# [v5.2 — 2026-03-13] textarea 활성화 클릭 추가 (ca-fe.naver.com 근본 원인 해결)
#   문제 확인 (실제 Actions 로그):
#     [dom] 댓글창 출현 감지: sel='.CommentWriter' ← 컨테이너 발견
#     [dom] 댓글 입력창 없음 — 모든 selector 실패 ← textarea는 hidden!
#   원인:
#     ca-fe.naver.com에서 textarea는 기본 display:none 상태
#     → .CommentWriter는 보이지만 내부 textarea는 not visible
#     → is_visible() 검사에서 COMMENT_INPUT_SELECTORS 전부 실패
#   수정:
#     _activate_comment_area(): frame 결정 후, textarea 탐색 전에
#     .comment_inbox 클릭 → 클릭 후 1.5초 대기 → textarea visible 상태 전환
#
# [v5.1 — 2026-03-13] 핵심 버그 2개 수정
#   버그 수정 1: _wait_for_comment_area() 반환값 활용 누락
#     기존: bool 반환 → submit_comment()가 결과 무시하고 _get_cafe_frame() 재호출
#           → _get_cafe_frame()이 외부 cafe.naver.com 페이지를 반환할 경우
#              내부 iframe의 U_cbox textarea를 찾지 못함
#     수정: Optional[tuple[frame, element]] 반환
#           → submit_comment()가 반환된 frame을 직접 사용 (재탐색 불필요)
#   버그 수정 2: 스크롤이 외부 페이지에만 적용
#     기존: page.evaluate("window.scrollTo(...)") → 외부 페이지만 스크롤
#           → 내부 iframe 안의 댓글창은 lazy rendering 미발동
#     수정: _wait_for_comment_area()가 감지한 frame 내부도 추가 스크롤
#
# [v5.0 — 2026-03-13] U_cbox 비동기 로드 대기 로직 추가
# [v4.0 — 2026-03-13] fe.naver.com/U_cbox selector 추가 + 전체 frame 탐색
# [v3.0 — 2026-03-13] iframe 재시도, Ctrl+Enter 폴백
# [v2.0 — 2026-03-11] frame_locator → page.frames Frame 객체 방식
# [v1.0 — 2026-03-09] 최초 작성
# ============================================================

import asyncio
import random
import logging
from typing import Optional, Tuple, Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# ── Selector 정의 (U_cbox 우선, 기존 시스템 폴백) ──

TITLE_SELECTORS = [
    ".title-text",
    "h3.title",
    ".ArticleTitle",
    ".article-title",
    ".tit_subject",
    "h3.tit_h3",
]
CONTENT_SELECTORS = [
    ".se-main-container",
    ".se-text-paragraph",
    ".tbody",
    ".article_body",
    ".se-module-text",
]
AUTHOR_SELECTORS = [
    ".writer-nick-wrap .nick",
    ".cafe-nick-name",
    ".writer_info .nick",
    ".m-tcol-c",
    ".nick",
]

# v5.0: 댓글창 출현 감지용 (가벼운 컨테이너 selector 우선)
# v5.1: _wait_for_comment_area()가 (frame, el) 반환 → submit_comment()에서 직접 활용
COMMENT_AREA_WAIT_SELECTORS = [
    ".u_cbox_write",            # U_cbox 입력 영역 컨테이너
    "textarea.u_cbox_text",     # U_cbox textarea 직접
    "#cbox_module",             # U_cbox 전체 모듈
    ".comment_inbox",           # 구형 시스템
    ".CommentWriter",           # 구형 시스템
    "textarea[placeholder*='댓글']",  # 범용 폴백
]

# 실제 textarea 탐색용 (더 구체적)
COMMENT_INPUT_SELECTORS = [
    # U_cbox 시스템 (fe.naver.com / 신규 카페)
    "textarea.u_cbox_text",
    "#cbox_module textarea",
    ".u_cbox_write textarea",
    ".u_cbox_write_box textarea",
    ".u_cbox_write_inner textarea",
    # 기존 시스템 (cafe.naver.com / 구형 카페)
    "textarea.comment_inbox_text",
    "textarea[placeholder*='댓글']",
    ".comment_inbox textarea",
    ".CommentWriter textarea",
    # 최후 폴백
    "textarea",
]

# 제출 버튼 탐색용
COMMENT_SUBMIT_SELECTORS = [
    # U_cbox 시스템
    ".u_cbox_btn_upload",
    "button.u_cbox_btn_upload",
    ".u_cbox_write_submit button",
    "button[class*='upload']",
    # 기존 시스템
    ".register_box button",
    ".register_box .btn_register",
    ".btn_write_comment",
    "button[class*='register']",
    "button[class*='submit']",
]


# ──────────────────────────────────────────
# Frame 객체 획득 (폴백용 — submit_comment에서는 우선순위 낮음)
# ──────────────────────────────────────────
async def _get_cafe_frame(page: Page):
    """
    게시글 Frame 객체 획득 (폴백용)
    순서: iframe 대기 → URL 매칭(3회 재시도) → name 매칭 → page 폴백

    v5.1 참고: submit_comment()에서는 _wait_for_comment_area()가 반환한
              frame을 우선 사용하므로, 이 함수는 보조 폴백 역할만 함
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        try:
            await page.wait_for_selector("iframe#cafe_main", timeout=5000)
        except Exception:
            logger.debug("[dom] iframe#cafe_main 미발견 (fe.naver.com 직접 접근)")

        for attempt in range(3):
            for frame in page.frames:
                if ("cafe.naver.com" in frame.url or
                    "ca-fe.naver.com" in frame.url or
                    "fe.naver.com" in frame.url or
                    "ArticleRead" in frame.url):
                    logger.debug(f"[dom] Frame 발견(URL): {frame.url[:70]}")
                    return frame
            if attempt < 2:
                await asyncio.sleep(1.0)

        named_frame = page.frame(name="cafe_main")
        if named_frame:
            logger.debug("[dom] Frame 발견(name=cafe_main)")
            return named_frame

        logger.warning(f"[dom] iframe 미발견 → page 직접 사용 ({len(page.frames)}개 frame)")
        for i, f in enumerate(page.frames):
            logger.debug(f"[dom]   frame[{i}] url='{f.url[:80]}'")
        return page

    except Exception as e:
        logger.warning(f"[dom] Frame 획득 예외 → page 폴백: {e}")
        return page


# ──────────────────────────────────────────
# v5.1 핵심 개선: 댓글창 출현 대기 → (frame, element) 반환
# ──────────────────────────────────────────
async def _wait_for_comment_area(
    page: Page,
    timeout_sec: float = 15.0,
) -> Optional[Tuple[Any, Any]]:
    """
    모든 frame을 폴링하며 댓글 입력창 컨테이너가 나타날 때까지 대기

    [v5.1 변경]
      반환값: (frame, element) 또는 None
      기존 bool 반환에서 변경 → submit_comment()가 frame을 직접 재활용
      가장 큰 변경점: 이 함수가 발견한 frame을 버리지 않음

    [v5.0 설계 의도]
      fe.naver.com에서 U_cbox가 JS로 비동기 초기화되므로
      domcontentloaded 후에도 바로 탐색하면 못 찾음
      → 1초 간격 폴링으로 실제 출현 시점 감지 (최대 15초)

    Returns:
        (frame, element) — 발견 시
        None             — 타임아웃 시
    """
    logger.info(f"[dom] 댓글창 출현 대기 시작 (최대 {timeout_sec:.0f}초)...")
    deadline = asyncio.get_event_loop().time() + timeout_sec

    while asyncio.get_event_loop().time() < deadline:
        for frame in page.frames:
            for sel in COMMENT_AREA_WAIT_SELECTORS:
                try:
                    el = frame.locator(sel).first
                    if await el.is_visible(timeout=800):
                        logger.info(
                            f"[dom] 댓글창 출현 감지: "
                            f"frame='{frame.url[:50]}' sel='{sel}'"
                        )
                        return frame, el   # ← v5.1: tuple 반환
                except Exception:
                    continue
        await asyncio.sleep(1.0)

    logger.warning(f"[dom] 댓글창 출현 대기 타임아웃 ({timeout_sec:.0f}초) — 강제 진행")
    return None   # ← v5.1: None 반환 (기존 False 대신)


# ──────────────────────────────────────────
# 전체 frame 순회 textarea 탐색
# ──────────────────────────────────────────
async def _find_textarea_in_any_frame(page: Page):
    """
    모든 frame을 순회하여 댓글 입력창 탐색
    Returns: (frame, element) 또는 (None, None)
    """
    for frame in page.frames:
        for sel in COMMENT_INPUT_SELECTORS:
            try:
                el = frame.locator(sel).first
                if await el.is_visible(timeout=1500):
                    logger.info(
                        f"[dom] 입력창 발견(전체 탐색): "
                        f"frame='{frame.url[:50]}' sel='{sel}'"
                    )
                    return frame, el
            except Exception:
                continue
    return None, None


# ──────────────────────────────────────────
# 요소 탐색 헬퍼
# ──────────────────────────────────────────
async def _find_el(target, selectors: list, label: str):
    for sel in selectors:
        try:
            el = target.locator(sel).first
            if await el.is_visible(timeout=3000):
                logger.debug(f"[dom] {label} 발견: '{sel}'")
                return el
        except Exception:
            continue
    logger.warning(f"[dom] {label} 없음 — 모든 selector 실패")
    return None


async def _debug_frames(page: Page):
    """실패 시 전체 frame 상태 디버그"""
    try:
        logger.debug("[dom] === Frame 디버그 ===")
        for fi, frame in enumerate(page.frames):
            try:
                fta = await frame.locator("textarea").all()
                logger.debug(
                    f"[dom] frame[{fi}] url='{frame.url[:60]}' textarea:{len(fta)}개"
                )
                for i, ta in enumerate(fta[:3]):
                    cls = await ta.get_attribute("class") or ""
                    ph  = await ta.get_attribute("placeholder") or ""
                    logger.debug(f"[dom]   [{i}] class='{cls}' ph='{ph}'")
            except Exception:
                logger.debug(f"[dom] frame[{fi}] url='{frame.url[:60]}' 탐색 불가")
        logger.debug("[dom] === Frame 디버그 종료 ===")
    except Exception:
        pass


# ──────────────────────────────────────────
# 게시글 내용 읽기
# ──────────────────────────────────────────
async def read_post_content(page: Page) -> tuple:
    """게시글 제목 / 내용 / 작성자 읽기"""
    async def try_sel(target, sels: list) -> str:
        for sel in sels:
            try:
                t = await target.locator(sel).first.text_content(timeout=4000)
                if t and t.strip():
                    return t.strip()
            except Exception:
                continue
        return ""

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        frame   = await _get_cafe_frame(page)
        title   = await try_sel(frame, TITLE_SELECTORS)
        content = await try_sel(frame, CONTENT_SELECTORS)
        author  = await try_sel(frame, AUTHOR_SELECTORS) or "알수없음"
        logger.debug(f"[dom] 게시글 읽기: '{title[:30]}' / {author}")
        return title, content, author
    except Exception as e:
        logger.error(f"[dom] 게시글 읽기 실패: {e}")
        return "", "", "알수없음"


# ──────────────────────────────────────────
# v5.2: 댓글창 클릭 활성화 (ca-fe.naver.com 전용)
# ──────────────────────────────────────────

# ca-fe.naver.com에서 textarea는 기본 hidden → 이 영역을 클릭해야 active됨
COMMENT_ACTIVATOR_SELECTORS = [
    ".comment_inbox",            # 구형/ca-fe.naver.com 댓글 입력 영역
    ".CommentWriter .comment_inbox",
    ".u_cbox_write",             # U_cbox 입력 영역
    ".u_cbox_write_area",
    ".CommentWriter",            # 최후 폴백 (컨테이너 전체 클릭)
]


async def _activate_comment_area(frame, label_url: str = "") -> bool:
    """
    댓글창을 클릭하여 textarea를 활성화(hidden → visible)

    ca-fe.naver.com에서 textarea는 기본적으로 display:none 상태.
    .comment_inbox 등의 컨테이너를 클릭해야 textarea가 나타남.

    Returns: True (활성화 성공 가능성 있음) / False (클릭 실패)
    """
    for sel in COMMENT_ACTIVATOR_SELECTORS:
        try:
            el = frame.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                logger.info(
                    f"[dom] 댓글창 클릭 활성화: '{sel}' "
                    f"frame='{label_url[:40]}'"
                )
                await asyncio.sleep(1.5)   # textarea가 나타날 때까지 대기
                return True
        except Exception:
            continue
    logger.debug("[dom] 댓글창 활성화 클릭 실패 (무시 — 이미 활성화 상태일 수 있음)")
    return False


# ──────────────────────────────────────────
# 댓글 입력 및 제출 (v5.2: textarea 활성화 클릭 추가)
# ──────────────────────────────────────────
async def submit_comment(page: Page, comment_text: str) -> bool:
    """
    댓글 입력창 탐색 → 텍스트 입력 → 제출

    [v5.2 핵심 수정]
      문제 확인 (실제 Actions 로그):
        [dom] 댓글창 출현 감지: frame='ca-fe.naver.com/...' sel='.CommentWriter'
        [dom] 댓글 입력창 없음 — 모든 selector 실패
      원인:
        ca-fe.naver.com에서 textarea는 기본 display:none 상태
        → .CommentWriter는 보이지만 textarea는 hidden
        → is_visible(timeout=3000) 검사에서 모두 실패
      수정:
        frame 결정 후, textarea 탐색 전에 .comment_inbox 클릭
        → 클릭으로 textarea 활성화(hidden→visible) 후 탐색

    [v5.1 수정 유지]
      - _wait_for_comment_area() 반환 frame 직접 사용
      - frame 내부 스크롤

    [v5.0 유지]
      - 15초 폴링 대기, 전체 frame 순회 폴백
      - type() → fill() → Ctrl+Enter 3단계 폴백
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # ── 1단계: 외부 페이지 스크롤 → 기본 lazy rendering 유발 ──
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.0)
        except Exception:
            pass

        # ── 2단계: 댓글창 출현 폴링 대기 (v5.1: frame 정보 반환) ──
        wait_result = await _wait_for_comment_area(page, timeout_sec=15.0)

        # ── 3단계: 감지된 frame 내부도 스크롤 (v5.1) ──
        detected_frame = None
        if wait_result:
            detected_frame, _ = wait_result
            if detected_frame and len(page.frames) > 1:
                try:
                    await detected_frame.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                    logger.debug(
                        f"[dom] frame 내부 스크롤 완료: '{detected_frame.url[:50]}'"
                    )
                    await asyncio.sleep(1.0)
                except Exception as scroll_err:
                    logger.debug(f"[dom] frame 내부 스크롤 불가 (무시): {scroll_err}")

        # ── 4단계: 탐색 대상 frame 결정 ──
        frame = detected_frame if detected_frame else await _get_cafe_frame(page)

        # ── 4.5단계: 댓글창 클릭 활성화 (v5.2 핵심 추가) ──
        # ca-fe.naver.com에서 textarea는 기본 hidden → 클릭해야 visible
        await _activate_comment_area(
            frame,
            label_url=detected_frame.url if detected_frame else "",
        )

        # ── 5단계: 활성화 후 textarea 탐색 ──
        input_el = await _find_el(frame, COMMENT_INPUT_SELECTORS, "댓글 입력창")

        # ── 6단계: 전체 frame 순회 2차 탐색 (최후 안전장치) ──
        if input_el is None:
            logger.info("[dom] 1차 탐색 실패 → 전체 frame 순회 탐색")
            # 다른 frame들에도 활성화 클릭 시도
            for f in page.frames:
                if f != frame:
                    await _activate_comment_area(f, label_url=f.url)
            frame, input_el = await _find_textarea_in_any_frame(page)

        if input_el is None:
            logger.error("[dom] 모든 frame에서 댓글 입력창 탐색 실패")
            await _debug_frames(page)
            return False

        # ── 텍스트 입력: type() → fill() 폴백 ──
        await input_el.click()
        await asyncio.sleep(random.uniform(0.5, 1.0))

        try:
            await input_el.type(comment_text, delay=random.randint(60, 120))
        except Exception as type_err:
            logger.warning(f"[dom] type() 실패 → fill() 폴백: {type_err}")
            try:
                await input_el.fill(comment_text)
            except Exception as fill_err:
                logger.error(f"[dom] fill() 도 실패: {fill_err}")
                return False

        await asyncio.sleep(random.uniform(0.8, 1.5))

        # ── 제출: 버튼 클릭 → Ctrl+Enter 폴백 ──
        submitted  = False
        submit_el  = await _find_el(frame, COMMENT_SUBMIT_SELECTORS, "제출 버튼")

        if submit_el is not None:
            try:
                await submit_el.click()
                submitted = True
                logger.debug("[dom] 버튼 클릭으로 제출")
            except Exception as click_err:
                logger.warning(f"[dom] 버튼 클릭 실패 → Ctrl+Enter 폴백: {click_err}")

        if not submitted:
            try:
                await input_el.press("Control+Enter")
                submitted = True
                logger.debug("[dom] Ctrl+Enter로 제출")
            except Exception as key_err:
                logger.error(f"[dom] Ctrl+Enter 도 실패: {key_err}")
                return False

        await asyncio.sleep(2.5)

        # ── 성공 검증: 입력창 초기화 여부 확인 ──
        try:
            after_value = await input_el.input_value()
            if after_value == "":
                logger.info("[dom] ✅ 댓글 제출 성공 (입력창 초기화 확인)")
            else:
                logger.warning("[dom] 입력창 내용 잔류 — 제출 실패 가능성")
        except Exception:
            logger.debug("[dom] 입력창 상태 확인 불가 — 제출 성공으로 간주")

        return submitted

    except Exception as e:
        logger.error(f"[dom] 댓글 제출 실패: {e}", exc_info=True)
        return False
