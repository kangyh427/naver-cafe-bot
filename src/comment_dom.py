# ============================================================
# 파일명: comment_dom.py
# 경로:   kangyh427/naver-cafe-bot/src/comment_dom.py
# 역할:   네이버 카페 게시글 DOM 접근 전담
#         (게시글 읽기 / 댓글 입력 및 제출)
#
# 작성일: 2026-03-11
# 수정일: 2026-03-13
# 버전:   v5.0
#
# [v5.0 — 2026-03-13] U_cbox 비동기 로드 대기 로직 추가
#   원인 확정:
#     fe.naver.com에서 U_cbox 댓글 시스템이 JS로 비동기 초기화됨
#     → 페이지 로드 완료(domcontentloaded) 시점에 댓글창이 DOM에 없음
#     → _find_textarea_in_any_frame()이 모든 frame을 뒤져도 못 찾음
#   수정:
#     - _wait_for_comment_area(): 모든 frame을 폴링하며 댓글창 출현 대기
#       최대 15초 대기, 1초 간격으로 재확인 (비동기 로드 완전 대응)
#     - submit_comment() 진입 시 _wait_for_comment_area() 먼저 호출
#     - 스크롤 후 추가 3초 대기 (lazy rendering 완전 대응)
#   안전장치:
#     - 15초 후에도 없으면 _find_textarea_in_any_frame()으로 최후 시도
#     - 전체 frame 디버그 로그 강화
#
# [v4.0 — 2026-03-13] fe.naver.com/U_cbox selector 추가 + 전체 frame 탐색
# [v3.0 — 2026-03-13] iframe 재시도, Ctrl+Enter 폴백
# [v2.0 — 2026-03-11] frame_locator → page.frames Frame 객체 방식
# [v1.0 — 2026-03-09] 최초 작성
# ============================================================

import asyncio
import random
import logging

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

# v5.0: 댓글창 출현 감지용 (대기에 사용, 가벼운 selector 우선)
COMMENT_AREA_WAIT_SELECTORS = [
    ".u_cbox_write",
    "textarea.u_cbox_text",
    "#cbox_module",
    ".comment_inbox",
    ".CommentWriter",
    "textarea[placeholder*='댓글']",
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
# Frame 객체 획득
# ──────────────────────────────────────────
async def _get_cafe_frame(page: Page):
    """
    게시글 Frame 객체 획득
    순서: iframe 대기 → URL 매칭(3회 재시도) → name 매칭 → page 폴백
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
# v5.0 핵심: 댓글창 출현 대기 (폴링 방식)
# ──────────────────────────────────────────
async def _wait_for_comment_area(page: Page, timeout_sec: float = 15.0) -> bool:
    """
    모든 frame을 폴링하며 댓글 입력창이 나타날 때까지 대기

    fe.naver.com에서 U_cbox가 JS로 비동기 초기화되므로
    domcontentloaded 후에도 바로 탐색하면 못 찾음
    → 1초 간격 폴링으로 실제 출현 시점 감지

    Returns: True (발견) / False (타임아웃)
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
                        return True
                except Exception:
                    continue
        await asyncio.sleep(1.0)

    logger.warning(f"[dom] 댓글창 출현 대기 타임아웃 ({timeout_sec:.0f}초) — 강제 진행")
    return False


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
# 댓글 입력 및 제출 (v5.0: 비동기 로드 대기 추가)
# ──────────────────────────────────────────
async def submit_comment(page: Page, comment_text: str) -> bool:
    """
    댓글 입력창 탐색 → 텍스트 입력 → 제출

    v5.0 핵심 수정:
      1. _wait_for_comment_area(): 댓글창 출현까지 폴링 대기 (최대 15초)
         fe.naver.com U_cbox 비동기 초기화 완전 대응
      2. 스크롤 후 추가 3초 대기 (lazy rendering 완전 대응)
      3. 1차 탐색 실패 시 _find_textarea_in_any_frame() 전체 탐색
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # ── 1단계: 하단 스크롤 → 댓글창 lazy rendering 유발 ──
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.0)   # 스크롤 후 추가 대기 (v5.0: 1.5→2.0초)
        except Exception:
            pass

        # ── 2단계: 댓글창 출현까지 폴링 대기 (v5.0 핵심 추가) ──
        await _wait_for_comment_area(page, timeout_sec=15.0)

        # ── 3단계: cafe frame 안에서 1차 탐색 ──
        frame    = await _get_cafe_frame(page)
        input_el = await _find_el(frame, COMMENT_INPUT_SELECTORS, "댓글 입력창")

        # ── 4단계: 전체 frame 순회 2차 탐색 ──
        if input_el is None:
            logger.info("[dom] 1차 탐색 실패 → 전체 frame 순회 탐색")
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
        submitted = False
        submit_el = await _find_el(frame, COMMENT_SUBMIT_SELECTORS, "제출 버튼")

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

        # ── 성공 검증: 입력창 초기화 여부 ──
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
