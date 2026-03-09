# ============================================================
# 파일명: cafe_monitor.py
# 경로:   kangyh427/naver_cafe_bot/src/cafe_monitor.py
# 역할:   네이버 카페 게시글/댓글 수집 + 스팸 댓글 삭제
#
# 작성일: 2026-03-09
# 버전:   v1.0
#
# 의존성:
#   - playwright (naver_login.py에서 page 수신)
#   - 환경변수: CAFE_URL (기본: https://cafe.naver.com/alexstock)
#
# 작동 흐름:
#   1. 전체글 보기 → 최신 게시글 15개 URL 수집
#   2. 각 게시글 진입 → 댓글 목록 수집
#   3. spam_detector.py로 스팸 판별
#   4. 스팸 댓글: 관리자 삭제 버튼 클릭
#   5. 신규 게시글 URL 목록 반환 (comment_writer.py로 전달)
#
# 안전장치:
#   - 각 게시글/댓글 처리 독립 try/except (1개 실패가 전체 중단 방지)
#   - 삭제 전 confirm 팝업 자동 처리
#   - 게시글 수집 실패 시 빈 목록 반환 (봇 중단 방지)
#   - CAFE_IFRAME: 네이버 카페는 iframe 구조 → 반드시 frame 전환 필요
# ============================================================

import os
import asyncio
import random
import logging
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Page

from spam_detector import is_spam
from supabase_logger import log_spam_deleted

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
CAFE_URL          = os.environ.get("CAFE_URL", "https://cafe.naver.com/alexstock")
POSTS_TO_MONITOR  = 15    # 최신 게시글 수집 개수
PAGE_LOAD_WAIT_S  = 2.0   # 페이지 로딩 대기 (초)
ACTION_DELAY_S    = 1.5   # 액션 간 대기 (초)


# ──────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────
@dataclass
class CommentInfo:
    """댓글 정보"""
    comment_id: str
    author:     str
    content:    str
    delete_btn_selector: Optional[str] = None  # 삭제 버튼 selector (관리자용)


@dataclass
class PostInfo:
    """게시글 정보"""
    url:     str
    title:   str
    author:  str
    is_new:  bool = False  # 처리된 적 없는 신규 글 여부
    comments: list[CommentInfo] = field(default_factory=list)


@dataclass
class MonitorResult:
    """모니터링 결과 통계"""
    posts_checked:  int = 0
    spam_deleted:   int = 0
    errors:         int = 0
    new_post_urls:  list[str] = field(default_factory=list)  # 환영 댓글 대상


# ──────────────────────────────────────────
# 카페 iframe 전환 헬퍼
# ──────────────────────────────────────────
async def _get_cafe_frame(page: Page):
    """
    네이버 카페는 iframe 구조 — 반드시 카페 frame으로 전환 필요
    Returns: frame 객체 / Page 객체 (iframe 없을 경우)
    """
    try:
        # 네이버 카페 메인 iframe
        frame = page.frame_locator("iframe#cafe_main").first
        return frame
    except Exception:
        logger.debug("[monitor] iframe 없음 — 직접 page 사용")
        return page


# ──────────────────────────────────────────
# 게시글 목록 수집
# ──────────────────────────────────────────
async def collect_recent_posts(page: Page) -> list[PostInfo]:
    """
    전체글 보기에서 최신 게시글 URL 수집
    Returns: PostInfo 목록 (최대 POSTS_TO_MONITOR개)
    """
    posts: list[PostInfo] = []

    try:
        # 전체글 보기 URL
        list_url = f"{CAFE_URL}?iframe_url=/ArticleList.nhn%3Fsearch.clubid=&search.boardtype=L"
        await page.goto(CAFE_URL, timeout=15000)
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        # iframe 전환
        frame = await _get_cafe_frame(page)

        # 게시글 링크 수집
        # 네이버 카페 게시글 목록 selector (카페 공통)
        post_links = await frame.locator("a.article").all()

        if not post_links:
            # 다른 selector 시도
            post_links = await frame.locator(".article-board a[href*='ArticleRead']").all()

        for link in post_links[:POSTS_TO_MONITOR]:
            try:
                href  = await link.get_attribute("href") or ""
                title = (await link.text_content() or "제목없음").strip()

                # 상대경로 → 절대경로 변환
                if href.startswith("/"):
                    url = f"https://cafe.naver.com{href}"
                elif href.startswith("http"):
                    url = href
                else:
                    continue

                # 글쓴이 추출 (링크 주변 요소)
                try:
                    author_el = link.locator("xpath=../..//td[@class='td_name']").first
                    author = (await author_el.text_content() or "알수없음").strip()
                except Exception:
                    author = "알수없음"

                posts.append(PostInfo(url=url, title=title, author=author))

            except Exception as e:
                logger.debug(f"[monitor] 게시글 링크 파싱 실패: {e}")
                continue

        logger.info(f"[monitor] 게시글 {len(posts)}개 수집 완료")

    except Exception as e:
        logger.error(f"[monitor] 게시글 목록 수집 실패: {e}")

    return posts


# ──────────────────────────────────────────
# 댓글 수집
# ──────────────────────────────────────────
async def collect_comments(page: Page, post: PostInfo) -> list[CommentInfo]:
    """
    게시글 페이지에서 댓글 목록 수집
    Returns: CommentInfo 목록
    """
    comments: list[CommentInfo] = []

    try:
        await page.goto(post.url, timeout=15000)
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_cafe_frame(page)

        # 댓글 컨테이너 (네이버 카페 공통 selector)
        comment_items = await frame.locator(".comment_list li.CommentItem").all()

        for idx, item in enumerate(comment_items):
            try:
                # 댓글 ID (data 속성 또는 인덱스)
                comment_id = await item.get_attribute("data-comment-id") or f"idx_{idx}"

                # 작성자
                author_el = item.locator(".comment_nickname, .nick").first
                author    = (await author_el.text_content() or "알수없음").strip()

                # 내용
                content_el = item.locator(".comment_text_box, .comment_body").first
                content    = (await content_el.text_content() or "").strip()

                if not content:
                    continue

                # 삭제 버튼 selector (관리자에게만 표시)
                delete_selector = f".comment_list li.CommentItem:nth-child({idx + 1}) .comment_delete, .btn_delete"

                comments.append(CommentInfo(
                    comment_id=comment_id,
                    author=author,
                    content=content,
                    delete_btn_selector=delete_selector,
                ))

            except Exception as e:
                logger.debug(f"[monitor] 댓글 파싱 실패 (idx:{idx}): {e}")
                continue

    except Exception as e:
        logger.error(f"[monitor] 댓글 수집 실패 [{post.url[:50]}]: {e}")

    return comments


# ──────────────────────────────────────────
# 스팸 댓글 삭제
# ──────────────────────────────────────────
async def delete_spam_comment(
    page: Page,
    post: PostInfo,
    comment: CommentInfo,
) -> bool:
    """
    스팸 댓글 관리자 삭제
    Returns: True (삭제 성공) / False (실패)
    """
    try:
        frame = await _get_cafe_frame(page)

        # 삭제 버튼 클릭
        delete_btn = frame.locator(comment.delete_btn_selector).first
        if not await delete_btn.is_visible(timeout=3000):
            logger.warning(f"[monitor] 삭제 버튼 없음 — 관리자 권한 확인: {comment.author}")
            return False

        await delete_btn.click()
        await asyncio.sleep(0.8)

        # 확인 팝업 처리 (alert/confirm)
        try:
            page.once("dialog", lambda d: asyncio.create_task(d.accept()))
        except Exception:
            pass

        await asyncio.sleep(random.uniform(1.0, 2.0))
        logger.info(f"[monitor] 스팸 댓글 삭제 성공: {comment.author} — '{comment.content[:30]}...'")
        return True

    except Exception as e:
        logger.error(f"[monitor] 댓글 삭제 실패: {e}")
        return False


# ──────────────────────────────────────────
# 메인 모니터링 실행
# ──────────────────────────────────────────
async def run_monitor(page: Page) -> MonitorResult:
    """
    전체 모니터링 실행 — 외부(main.py)에서 호출하는 단일 진입점
    Args:
        page: 로그인된 네이버 페이지 (naver_login.py에서 수신)
    Returns:
        MonitorResult (통계 + 신규 게시글 URL 목록)
    """
    result = MonitorResult()

    # 1. 게시글 목록 수집
    posts = await collect_recent_posts(page)
    if not posts:
        logger.warning("[monitor] 수집된 게시글 없음")
        return result

    # 2. 각 게시글 처리
    for post in posts:
        result.posts_checked += 1

        try:
            # 댓글 수집
            comments = await collect_comments(page, post)
            post.comments = comments

            # 3. 각 댓글 스팸 판별 + 삭제
            for comment in comments:
                try:
                    spam_flag, reason = is_spam(
                        comment_text=comment.content,
                        post_context=post.title,
                    )

                    if spam_flag:
                        deleted = await delete_spam_comment(page, post, comment)
                        if deleted:
                            result.spam_deleted += 1
                            # DB 로그 저장
                            log_spam_deleted(
                                post_url=post.url,
                                comment_author=comment.author,
                                comment_content=comment.content,
                                spam_reason=reason,
                            )

                except Exception as e:
                    logger.error(f"[monitor] 댓글 처리 오류: {e}")
                    result.errors += 1

            # 4. 신규 게시글 URL 수집 (comment_writer.py로 전달)
            result.new_post_urls.append(post.url)

            # 게시글 간 랜덤 딜레이 (계정 보호)
            await asyncio.sleep(random.uniform(ACTION_DELAY_S, ACTION_DELAY_S + 1.5))

        except Exception as e:
            logger.error(f"[monitor] 게시글 처리 오류 [{post.url[:50]}]: {e}")
            result.errors += 1

    logger.info(
        f"[monitor] 완료 | "
        f"게시글:{result.posts_checked} 스팸삭제:{result.spam_deleted} "
        f"신규:{len(result.new_post_urls)} 오류:{result.errors}"
    )
    return result
