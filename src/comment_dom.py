# ============================================================
# 파일명: comment_dom.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_dom.py
# 역할:   네이버 카페 게시글 DOM 접근 전담
#
# 작성일: 2026-03-11
# 버전:   v2.0
#
# [v2.0] 근본 수정: frame_locator → page.frames Frame 객체 방식
#
#   확정 DOM 구조 (크롬 개발자도구 직접 확인):
#     iframe#cafe_main > ... > div.CommentWriter >
#     div.comment_inbox > textarea.comment_inbox_text
#
#   오류 원인:
#     frame_locator()는 요소 탐색 헬퍼 — type()/click() 액션 불가
#     page.frames로 실제 Frame 객체를 얻어야 액션 실행 가능
#
# 안전장치:
#   - Frame 탐색 3단계 폴백 (URL → name → page 직접)
#   - 댓글 입력창/제출버튼 다중 selector
#   - 실패 시 모든 frame의 textarea 디버그 출력
# ============================================================

import asyncio
import random
import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# ── Selector (DOM 직접 확인 기준) ──
TITLE_SELECTORS = [
    ".title-text", "h3.title", ".ArticleTitle",
    ".article-title", ".tit_subject",
]
CONTENT_SELECTORS = [
    ".se-main-container", ".se-text-paragraph",
    ".tbody", ".article_body",
]
AUTHOR_SELECTORS = [
    ".writer-nick-wrap .nick", ".cafe-nick-name",
    ".writer_info .nick", ".m-tcol-c",
]
COMMENT_INPUT_SELECTORS = [
    "textarea.comment_inbox_text",
    "textarea[placeholder*='댓글']",
    ".comment_inbox textarea",
    ".CommentWriter textarea",
]
COMMENT_SUBMIT_SELECTORS = [
    ".register_box button",
    ".register_box .btn_register",
    ".btn_write_comment",
]


async def _get_cafe_frame(page: Page):
    """
    iframe#cafe_main의 Frame 객체 획득
    Frame 객체여야 type(), click() 실행 가능

    순서: URL 매칭 → name 매칭 → page 폴백
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # 1차: URL 기반 (가장 신뢰)
        for frame in page.frames:
            url = frame.url
            if "cafe.naver.com" in url or "ca-fe.naver.com" in url:
                logger.debug(f"[dom] frame 발견(URL): {url[:60]}")
                return frame

        # 2차: name 기반
        frame = page.frame(name="cafe_main")
        if frame:
            logger.debug("[dom] frame 발견(name=cafe_main)")
            return frame

        # 3차: 폴백
        logger.debug(f"[dom] iframe 없음 → page 직접 (총 {len(page.frames)}개 frame)")
        for i, f in enumerate(page.frames):
            logger.debug(f"[dom]   frame[{i}] {f.url[:60]}")
        return page

    except Exception as e:
        logger.debug(f"[dom] frame 획득 실패 → page: {e}")
        return page


async def _find_el(target, selectors, label):
    """selector 순서대로 탐색, 발견 시 반환"""
    for sel in selectors:
        try:
            el = target.locator(sel).first
            if await el.is_visible(timeout=3000):
                logger.debug(f"[dom] {label} 발견: '{sel}'")
                return el
        except Exception:
            continue
    logger.error(f"[dom] {label} 없음 — 모든 selector 실패")
    return None


async def _debug_frames(page: Page):
    """실패 시 전체 frame의 textarea 디버그"""
    try:
        for fi, frame in enumerate(page.frames):
            try:
                fta = await frame.locator("textarea").all()
                if fta:
                    logger.debug(f"[dom] frame[{fi}] ({frame.url[:40]}) textarea {len(fta)}개")
                    for i, ta in enumerate(fta[:3]):
                        cls = await ta.get_attribute("class") or ""
                        logger.debug(f"[dom]     [{i}] class='{cls}'")
            except Exception:
                pass
    except Exception:
        pass


async def read_post_content(page: Page) -> tuple[str, str, str]:
    """게시글 제목/내용/작성자 읽기"""
    async def try_sel(target, sels):
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
        frame = await _get_cafe_frame(page)
        title   = await try_sel(frame, TITLE_SELECTORS)
        content = await try_sel(frame, CONTENT_SELECTORS)
        author  = await try_sel(frame, AUTHOR_SELECTORS) or "알수없음"
        logger.debug(f"[dom] 읽기: '{title[:30]}' / {author}")
        return title, content, author
    except Exception as e:
        logger.error(f"[dom] 게시글 읽기 실패: {e}")
        return "", "", "알수없음"


async def submit_comment(page: Page, comment_text: str) -> bool:
    """댓글 입력 및 제출"""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        frame = await _get_cafe_frame(page)

        # 입력창 탐색
        input_el = await _find_el(frame, COMMENT_INPUT_SELECTORS, "입력창")
        if input_el is None:
            await _debug_frames(page)
            return False

        # 타이핑
        await input_el.click()
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await input_el.type(comment_text, delay=random.randint(60, 130))
        await asyncio.sleep(random.uniform(0.8, 1.5))

        # 제출 버튼
        submit_el = await _find_el(frame, COMMENT_SUBMIT_SELECTORS, "제출버튼")
        if submit_el is None:
            return False

        await submit_el.click()
        await asyncio.sleep(2.5)

        # 성공 검증
        try:
            after = await input_el.input_value()
            if after == "":
                logger.info("[dom] 제출 성공 (입력창 초기화 확인)")
            else:
                logger.warning("[dom] 입력창 내용 잔류 — 제출 실패 가능")
        except Exception:
            pass

        return True

    except Exception as e:
        logger.error(f"[dom] 댓글 제출 실패: {e}", exc_info=True)
        return False
