# ============================================================
# 파일명: comment_dom.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_dom.py
# 역할:   네이버 카페 게시글 DOM 접근 전담
#         - 게시글 제목/내용/작성자 읽기
#         - 댓글 입력 및 제출
#
# 작성일: 2026-03-11
# 버전:   v1.0
#
# 근본 문제 수정:
#   [이전 v4.0 오류] "댓글창은 iframe 안이 아닌 메인 페이지에 직접 렌더링"이라는
#   잘못된 가정으로 iframe 로직을 완전 제거함.
#   → 실제로 네이버 카페 게시글은 iframe#cafe_main 안에 렌더링됨.
#   → cafe_monitor.py는 iframe을 계속 사용 중이었는데
#     comment_writer.py만 iframe 제거 → selector 탐색 실패
#
#   [v1.0 수정] iframe 우선 탐색 + page 직접 접근 폴백
#     1차: iframe#cafe_main 안에서 textarea 탐색
#     2차: page 직접에서 textarea 탐색
#     → 어느 쪽이든 찾으면 댓글 작성 진행
#
# 안전장치:
#   - iframe 탐색 실패 시 page 직접 접근으로 자동 폴백
#   - 댓글 입력창 다중 selector 후보
#   - 제출 버튼 다중 selector 후보
#   - 제출 성공 검증 (입력창 초기화 확인)
#   - 실패 시 현재 DOM 구조 디버그 로그 출력
# ============================================================

import asyncio
import random
import logging
from typing import Optional

from playwright.async_api import Page, FrameLocator

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# Selector 후보 목록
# ──────────────────────────────────────────

# 게시글 정보 selector
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
    ".post-content",
]

AUTHOR_SELECTORS = [
    ".writer-nick-wrap .nick",
    ".cafe-nick-name",
    ".writer_info .nick",
    ".m-tcol-c",
]

# 댓글 입력창 selector 후보 (우선순위 순)
COMMENT_INPUT_SELECTORS = [
    "textarea.comment_inbox_text",
    "textarea[placeholder*='댓글']",
    "textarea[name='content']",
    ".CommentWriter textarea",
    ".comment_write textarea",
    ".comment_inbox textarea",
]

# 제출 버튼 selector 후보
COMMENT_SUBMIT_SELECTORS = [
    ".register_box button",
    ".register_box .btn_register",
    ".comment_write button[type='submit']",
    ".btn_write_comment",
    ".comment_submit",
]

# ──────────────────────────────────────────
# iframe 안전 획득
# ──────────────────────────────────────────

async def _get_content_frame(page: Page):
    """
    iframe#cafe_main 획득 시도 → 실패 시 page 반환
    네이버 카페는 iframe 안에 콘텐츠가 있으나,
    일부 URL은 page 직접 렌더링하므로 양쪽 모두 지원

    Returns:
        frame_locator 또는 page (둘 다 locator() 메서드 지원)
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        frame = page.frame_locator("iframe#cafe_main")
        # iframe 존재 여부 빠르게 확인
        count = await page.locator("iframe#cafe_main").count()
        if count > 0:
            logger.debug("[dom] iframe#cafe_main 발견 → iframe 사용")
            return frame
        else:
            logger.debug("[dom] iframe 없음 → page 직접 사용")
            return page
    except Exception as e:
        logger.debug(f"[dom] iframe 획득 실패 → page 직접 사용: {e}")
        return page


# ──────────────────────────────────────────
# 게시글 내용 읽기
# ──────────────────────────────────────────

async def read_post_content(page: Page) -> tuple[str, str, str]:
    """
    게시글 제목 / 내용 / 작성자 읽기
    iframe 우선, 실패 시 page 직접 접근

    Returns:
        (title, content, author)
    """
    async def try_selectors(frame, selectors: list[str]) -> str:
        for sel in selectors:
            try:
                text = await frame.locator(sel).first.text_content(timeout=4000)
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return ""

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        frame = await _get_content_frame(page)

        title   = await try_selectors(frame, TITLE_SELECTORS)
        content = await try_selectors(frame, CONTENT_SELECTORS)
        author  = await try_selectors(frame, AUTHOR_SELECTORS) or "알수없음"

        # iframe에서 못 찾으면 page 직접 시도
        if not title and frame is not page:
            logger.debug("[dom] iframe에서 제목 못 찾음 → page 직접 시도")
            title   = await try_selectors(page, TITLE_SELECTORS)
            content = await try_selectors(page, CONTENT_SELECTORS)
            author  = await try_selectors(page, AUTHOR_SELECTORS) or "알수없음"

        logger.debug(f"[dom] 읽기 완료: '{title[:30]}' / {author}")
        return title, content, author

    except Exception as e:
        logger.error(f"[dom] 게시글 읽기 실패: {e}")
        return "", "", "알수없음"


# ──────────────────────────────────────────
# 댓글 입력창 탐색 (iframe + page 양쪽)
# ──────────────────────────────────────────

async def _find_comment_input(page: Page):
    """
    댓글 입력창 탐색: iframe 우선 → page 직접 순으로 시도
    핵심 수정: iframe과 page 양쪽 모두에서 탐색

    Returns:
        (locator, frame_or_page) 또는 (None, None)
    """
    targets = []

    # 1차: iframe 시도
    iframe_count = await page.locator("iframe#cafe_main").count()
    if iframe_count > 0:
        targets.append(("iframe", page.frame_locator("iframe#cafe_main")))

    # 2차: page 직접
    targets.append(("page", page))

    for target_name, target in targets:
        for sel in COMMENT_INPUT_SELECTORS:
            try:
                el = target.locator(sel).first
                # FrameLocator는 count() 미지원 → is_visible 직접 시도
                if target_name == "iframe":
                    is_vis = await el.is_visible(timeout=3000)
                else:
                    count = await el.count()
                    is_vis = count > 0 and await el.is_visible(timeout=2000)

                if is_vis:
                    logger.info(f"[dom] 댓글 입력창 발견: [{target_name}] '{sel}'")
                    return el, target
            except Exception:
                continue

    # 실패 시 디버그 정보 출력
    logger.error("[dom] 댓글 입력창을 찾을 수 없음 — 모든 selector 실패")
    try:
        all_ta = await page.locator("textarea").all()
        logger.debug(f"[dom] 현재 페이지 textarea 수: {len(all_ta)}")
        for i, ta in enumerate(all_ta[:5]):
            cls = await ta.get_attribute("class") or ""
            ph  = await ta.get_attribute("placeholder") or ""
            logger.debug(f"[dom]   [{i}] class='{cls}' placeholder='{ph}'")
    except Exception:
        pass

    return None, None


# ──────────────────────────────────────────
# 댓글 제출
# ──────────────────────────────────────────

async def submit_comment(page: Page, comment_text: str) -> bool:
    """
    댓글 입력 및 제출
    iframe 우선 탐색 + page 직접 폴백으로 입력창 찾기

    Returns:
        True (성공) / False (실패)
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # 1. 입력창 탐색
        input_el, frame = await _find_comment_input(page)
        if input_el is None:
            return False

        # 2. 비활성화 확인
        try:
            if await input_el.is_disabled():
                logger.error("[dom] 입력창 비활성화 — 로그인 상태 확인 필요")
                return False
        except Exception:
            pass  # FrameLocator 환경에서 is_disabled 미지원 시 무시

        # 3. 타이핑
        await input_el.click()
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await input_el.type(comment_text, delay=random.randint(60, 130))
        await asyncio.sleep(random.uniform(0.8, 1.5))

        # 4. 입력 확인
        try:
            typed = await input_el.input_value()
            if not typed:
                logger.error("[dom] 입력 후 내용 비어있음")
                return False
        except Exception:
            pass  # FrameLocator 환경에서 input_value 불가 시 무시

        # 5. 제출 버튼 탐색 및 클릭
        submit_el = await _find_submit_button(frame)
        if submit_el is None:
            logger.error("[dom] 제출 버튼을 찾을 수 없음")
            return False

        await submit_el.click()
        await asyncio.sleep(2.5)

        # 6. 성공 검증 (입력창 초기화 여부)
        try:
            after_value = await input_el.input_value()
            if after_value == "":
                logger.debug("[dom] 제출 성공 확인 (입력창 초기화됨)")
            else:
                logger.warning("[dom] 제출 후 입력창 내용 남아있음 — 실패 가능성")
        except Exception:
            pass

        return True

    except Exception as e:
        logger.error(f"[dom] 댓글 제출 실패: {e}", exc_info=True)
        return False


async def _find_submit_button(frame):
    """제출 버튼 탐색 (frame 또는 page 내에서)"""
    for sel in COMMENT_SUBMIT_SELECTORS:
        try:
            el = frame.locator(sel).first
            is_vis = await el.is_visible(timeout=3000)
            if is_vis:
                logger.debug(f"[dom] 제출 버튼 발견: '{sel}'")
                return el
        except Exception:
            continue
    return None
