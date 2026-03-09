# ============================================================
# 파일명: cafe_monitor.py
# 경로:   kangyh427/naver_cafe_bot/src/cafe_monitor.py
# 역할:   네이버 카페 게시글/댓글 수집 + 스팸 댓글 삭제
#
# 작성일: 2026-03-09
# 수정일: 2026-03-10
# 버전:   v2.0
#
# [v2.0 — 2026-03-10]
#   Bug Fix: Execution context was destroyed (navigation)
#     - 원인: page.goto() 후 기존 frame 참조가 무효화됨
#     - 수정: 모든 frame 참조를 page.goto() 이후에 새로 획득
#             wait_for_load_state("domcontentloaded") 추가
#             게시글 이동 시 iframe 재획득 강제화
#
# [v1.0 — 2026-03-09]
#   최초 작성
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
POSTS_TO_MONITOR  = 15
PAGE_LOAD_WAIT_S  = 3.0     # v2.0: 2.0 → 3.0
ACTION_DELAY_S    = 1.5


# ──────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────
@dataclass
class CommentInfo:
    comment_id:          str
    author:              str
    content:             str
    delete_btn_selector: Optional[str] = None

@dataclass
class PostInfo:
    url:      str
    title:    str
    author:   str
    is_new:   bool = False
    comments: list[CommentInfo] = field(default_factory=list)

@dataclass
class MonitorResult:
    posts_checked:  int = 0
    spam_deleted:   int = 0
    errors:         int = 0
    new_post_urls:  list[str] = field(default_factory=list)


# ──────────────────────────────────────────
# iframe 안전 획득 (v2.0 핵심 수정)
# ──────────────────────────────────────────
async def _get_fresh_frame(page: Page):
    """
    페이지 로드 완료 후 항상 새 frame 참조 획득
    안전장치: iframe 없으면 page 직접 반환
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        return page.frame_locator("iframe#cafe_main").first
    except Exception:
        logger.debug("[monitor] iframe 없음 → page 직접 사용")
        return page


# ──────────────────────────────────────────
# 게시글 목록 수집
# ──────────────────────────────────────────
async def collect_recent_posts(page: Page) -> list[PostInfo]:
    """전체글 보기에서 최신 게시글 URL 수집"""
    posts: list[PostInfo] = []

    try:
        await page.goto(CAFE_URL, timeout=20000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        # v2.0: goto 이후 frame 새로 획득
        frame = await _get_fresh_frame(page)

        post_links = await frame.locator("a.article").all()
        if not post_links:
            post_links = await frame.locator(".article-board a[href*='ArticleRead']").all()

        for link in post_links[:POSTS_TO_MONITOR]:
            try:
                href  = await link.get_attribute("href") or ""
                title = (await link.text_content() or "제목없음").strip()

                if href.startswith("/"):
                    url = f"https://cafe.naver.com{href}"
                elif href.startswith("http"):
                    url = href
                else:
                    continue

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
# 댓글 수집 (v2.0 핵심 수정)
# ──────────────────────────────────────────
async def collect_comments(page: Page, post: PostInfo) -> list[CommentInfo]:
    """
    게시글 페이지에서 댓글 목록 수집
    v2.0: goto 이후 반드시 새 frame 획득
    """
    comments: list[CommentInfo] = []

    try:
        # v2.0: domcontentloaded 대기 후 frame 재획득
        await page.goto(post.url, timeout=20000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_fresh_frame(page)  # ← 핵심 수정

        comment_items = await frame.locator(".comment_list li.CommentItem").all()

        for idx, item in enumerate(comment_items):
            try:
                comment_id = await item.get_attribute("data-comment-id") or f"idx_{idx}"

                author_el = item.locator(".comment_nickname, .nick").first
                author    = (await author_el.text_content() or "알수없음").strip()

                content_el = item.locator(".comment_text_box, .comment_body").first
                content    = (await content_el.text_content() or "").strip()

                if not content:
                    continue

                delete_selector = (
                    f".comment_list li.CommentItem:nth-child({idx + 1}) "
                    f".comment_delete, .btn_delete"
                )

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
    """스팸 댓글 관리자 삭제"""
    try:
        frame = await _get_fresh_frame(page)  # v2.0: 매번 새로 획득

        delete_btn = frame.locator(comment.delete_btn_selector).first
        if not await delete_btn.is_visible(timeout=5000):
            logger.warning(f"[monitor] 삭제 버튼 없음: {comment.author}")
            return False

        await delete_btn.click()
        await asyncio.sleep(0.8)

        # 확인 팝업 처리
        try:
            page.once("dialog", lambda d: asyncio.create_task(d.accept()))
        except Exception:
            pass

        await asyncio.sleep(random.uniform(1.0, 2.0))
        logger.info(f"[monitor] 스팸 삭제 성공: {comment.author} — '{comment.content[:30]}'")
        return True

    except Exception as e:
        logger.error(f"[monitor] 댓글 삭제 실패: {e}")
        return False


# ──────────────────────────────────────────
# 메인 모니터링 실행
# ──────────────────────────────────────────
async def run_monitor(page: Page) -> MonitorResult:
    """
    전체 모니터링 실행 — main.py에서 호출하는 단일 진입점
    """
    result = MonitorResult()

    posts = await collect_recent_posts(page)
    if not posts:
        logger.warning("[monitor] 수집된 게시글 없음")
        return result

    for post in posts:
        result.posts_checked += 1

        try:
            # 댓글 수집 (v2.0: 내부에서 frame 새로 획득)
            comments = await collect_comments(page, post)
            post.comments = comments

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
                            log_spam_deleted(
                                post_url=post.url,
                                comment_author=comment.author,
                                comment_content=comment.content,
                                spam_reason=reason,
                            )

                except Exception as e:
                    logger.error(f"[monitor] 댓글 처리 오류: {e}")
                    result.errors += 1

            result.new_post_urls.append(post.url)

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
