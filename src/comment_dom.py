# ============================================================
# 파일명: comment_dom.py
# 경로:   kangyh427/naver-cafe-bot/src/comment_dom.py
# 역할:   네이버 카페 게시글 DOM 접근 전담
#         (게시글 읽기 / 댓글 입력 및 제출)
#
# 작성일: 2026-03-11
# 수정일: 2026-03-13
# 버전:   v3.0
#
# [v3.0 — 2026-03-13] 환영 댓글 0건 문제 근본 수정
#   버그 수정: iframe URL 탐색 실패 시 폴백이 page라 textarea 못 찾던 문제
#   개선 1: iframe URL 탐색에 재시도 루프 추가 (3회, 1초 간격)
#   개선 2: 댓글 입력 전 페이지 하단 스크롤 (lazy rendering 대응)
#   개선 3: 제출 실패 시 Ctrl+Enter 키보드 폴백 추가
#   개선 4: 입력 실패 시 type() → fill() 폴백 추가
#   개선 5: 전체 frame 디버그 로그 강화
#
# [v2.0 — 2026-03-11] frame_locator → page.frames Frame 객체 방식으로 수정
# [v1.0 — 2026-03-09] 최초 작성
# ============================================================

import asyncio
import random
import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# ── Selector 정의 (우선순위 순) ──
TITLE_SELECTORS = [
    ".title-text",
    "h3.title",
    ".ArticleTitle",
    ".article-title",
    ".tit_subject",
]
CONTENT_SELECTORS = [
    ".se-main-container",
    ".se-text-paragraph",
    ".tbody",
    ".article_body",
]
AUTHOR_SELECTORS = [
    ".writer-nick-wrap .nick",
    ".cafe-nick-name",
    ".writer_info .nick",
    ".m-tcol-c",
]
COMMENT_INPUT_SELECTORS = [
    "textarea.comment_inbox_text",
    "textarea[placeholder*='댓글']",
    ".comment_inbox textarea",
    ".CommentWriter textarea",
    "textarea",                     # 최후 폴백
]
COMMENT_SUBMIT_SELECTORS = [
    ".register_box button",
    ".register_box .btn_register",
    ".btn_write_comment",
    "button[class*='register']",
    "button[class*='submit']",
]


# ──────────────────────────────────────────
# Frame 객체 획득 (v3.0 강화)
# ──────────────────────────────────────────
async def _get_cafe_frame(page: Page):
    """
    iframe#cafe_main의 Frame 객체 획득
    Frame 객체여야 type(), click() 등 액션 실행 가능

    v3.0 개선: 재시도 루프 추가, 디버그 강화
    순서: iframe 대기 → URL 매칭(3회 재시도) → name 매칭 → page 폴백
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # iframe이 DOM에 나타날 때까지 최대 5초 대기
        try:
            await page.wait_for_selector("iframe#cafe_main", timeout=5000)
        except Exception:
            logger.debug("[dom] iframe#cafe_main 미발견 (타임아웃)")

        # 1차: URL 기반 탐색 (3회 재시도)
        for attempt in range(3):
            for frame in page.frames:
                if ("cafe.naver.com" in frame.url or
                    "ca-fe.naver.com" in frame.url or
                    "ArticleRead" in frame.url):
                    logger.debug(f"[dom] Frame 발견(URL): {frame.url[:60]}")
                    return frame
            if attempt < 2:
                await asyncio.sleep(1.0)
                logger.debug(f"[dom] Frame 재탐색 중 ({attempt + 2}/3)...")

        # 2차: name 기반
        named_frame = page.frame(name="cafe_main")
        if named_frame:
            logger.debug("[dom] Frame 발견(name=cafe_main)")
            return named_frame

        # 3차: 폴백 — page 직접 (전체 frame 목록 디버그)
        logger.warning(
            f"[dom] iframe 미발견 → page 직접 사용 "
            f"(총 {len(page.frames)}개 frame)"
        )
        for i, f in enumerate(page.frames):
            logger.debug(f"[dom]   frame[{i}] url='{f.url[:80]}'")
        return page

    except Exception as e:
        logger.warning(f"[dom] Frame 획득 예외 → page 폴백: {e}")
        return page


# ──────────────────────────────────────────
# 요소 탐색 헬퍼
# ──────────────────────────────────────────
async def _find_el(target, selectors: list, label: str):
    """selector 우선순위 순으로 탐색, 발견 시 반환"""
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
    """제출 실패 시 전체 frame의 textarea 상태 디버그 출력"""
    try:
        logger.debug("[dom] === Frame 디버그 시작 ===")
        for fi, frame in enumerate(page.frames):
            try:
                fta = await frame.locator("textarea").all()
                if fta:
                    logger.debug(f"[dom] frame[{fi}] ({frame.url[:50]}) textarea {len(fta)}개")
                    for i, ta in enumerate(fta[:3]):
                        cls         = await ta.get_attribute("class") or ""
                        placeholder = await ta.get_attribute("placeholder") or ""
                        logger.debug(f"[dom]   [{i}] class='{cls}' placeholder='{placeholder}'")
            except Exception:
                pass
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
# 댓글 입력 및 제출 (v3.0 강화)
# ──────────────────────────────────────────
async def submit_comment(page: Page, comment_text: str) -> bool:
    """
    댓글 입력창 탐색 → 텍스트 입력 → 제출

    v3.0 개선:
      - 입력 전 페이지 하단 스크롤 (textarea lazy rendering 대응)
      - 입력 방식: type() 실패 시 fill() 폴백
      - 제출 방식: 버튼 클릭 실패 시 Ctrl+Enter 키보드 폴백
      - 성공 검증: 입력창 초기화 여부 확인
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # 페이지 하단 스크롤 → 댓글창 lazy rendering 강제 로드
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
        except Exception:
            pass

        frame = await _get_cafe_frame(page)

        # ── 입력창 탐색 ──
        input_el = await _find_el(frame, COMMENT_INPUT_SELECTORS, "댓글 입력창")
        if input_el is None:
            await _debug_frames(page)
            return False

        # ── 텍스트 입력: type() → fill() 폴백 ──
        await input_el.click()
        await asyncio.sleep(random.uniform(0.5, 1.0))

        try:
            # type()은 실제 키보드 타이핑 시뮬레이션 (더 자연스러움)
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
                logger.warning(f"[dom] 입력창에 내용 잔류 — 제출 실패 가능")
        except Exception:
            # 페이지 리로드 등으로 입력창이 사라진 경우 → 제출 성공으로 판단
            logger.debug("[dom] 입력창 상태 확인 불가 — 제출 성공으로 간주")

        return submitted

    except Exception as e:
        logger.error(f"[dom] 댓글 제출 실패: {e}", exc_info=True)
        return False
