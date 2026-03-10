# ============================================================
# 파일명: cafe_monitor.py
# 경로:   kangyh427/naver_cafe_bot/src/cafe_monitor.py
# 역할:   네이버 카페 게시글/댓글 수집 + 스팸 댓글 삭제
#
# 작성일: 2026-03-09
# 수정일: 2026-03-10
# 버전:   v2.1
#
# [v2.1 — 2026-03-10]
#   변경: 최근 1일 이내 게시글만 처리하도록 필터 추가
#     - 이유: 하루 3번 실행 전환에 맞춰 오래된 글 재처리 방지
#     - 게시글 날짜를 파싱하여 24시간 초과 게시글 스킵
#     - 날짜 파싱 실패 시 안전하게 포함 (처리 누락 방지 우선)
#
# [v2.0 — 2026-03-10]
#   Bug Fix: Execution context was destroyed
#     - goto() 후 frame을 항상 새로 획득
#     - wait_for_load_state("domcontentloaded") 추가
#
# [v1.0 — 2026-03-09]
#   최초 작성
# ============================================================

import os
import asyncio
import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from playwright.async_api import Page

from spam_detector import is_spam
from supabase_logger import log_spam_deleted

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
CAFE_URL          = os.environ.get("CAFE_URL", "https://cafe.naver.com/alexstock")
POSTS_TO_MONITOR  = 15           # 수집 후 날짜 필터링하므로 여유있게 수집
PAGE_LOAD_WAIT_S  = 3.0
ACTION_DELAY_S    = 1.5
POST_MAX_AGE_HOURS = 24          # 24시간 이내 게시글만 처리


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
    url:        str
    title:      str
    author:     str
    posted_at:  Optional[datetime] = None   # v2.1: 게시 시각 추가
    is_new:     bool = False
    comments:   list[CommentInfo] = field(default_factory=list)

@dataclass
class MonitorResult:
    posts_checked:  int = 0
    spam_deleted:   int = 0
    errors:         int = 0
    new_post_urls:  list[str] = field(default_factory=list)


# ──────────────────────────────────────────
# iframe 안전 획득
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
# 게시글 날짜 파싱 (v2.1 신규)
# ──────────────────────────────────────────
def _parse_post_date(date_text: str) -> Optional[datetime]:
    """
    네이버 카페 날짜 텍스트 → datetime 변환
    지원 형식: "2026.03.10.", "03.10. 15:30", "15:30" (오늘)
    안전장치: 파싱 실패 시 None 반환 → 호출부에서 포함 처리
    """
    now = datetime.now(timezone.utc)
    text = date_text.strip()

    try:
        # 형식 1: "2026.03.10. 15:30" 또는 "2026.03.10."
        if text.count('.') >= 3:
            clean = text.replace(' ', '').rstrip('.')
            parts = clean.split('.')
            if len(parts) >= 3:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                return datetime(year, month, day, tzinfo=timezone.utc)

        # 형식 2: "03.10. 15:30" (연도 없음 → 올해)
        if text.count('.') == 2:
            clean = text.replace(' ', '').rstrip('.')
            parts = clean.split('.')
            month, day = int(parts[0]), int(parts[1])
            return datetime(now.year, month, day, tzinfo=timezone.utc)

        # 형식 3: "15:30" (오늘 시각)
        if ':' in text and '.' not in text:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)

    except (ValueError, IndexError):
        pass

    return None  # 파싱 실패 → 호출부에서 포함 처리


def _is_within_24h(posted_at: Optional[datetime]) -> bool:
    """
    24시간 이내 게시글인지 확인
    안전장치: 날짜 파싱 실패(None) 시 True 반환 (처리 누락 방지 우선)
    """
    if posted_at is None:
        return True  # 파싱 실패 → 안전하게 포함
    cutoff = datetime.now(timezone.utc) - timedelta(hours=POST_MAX_AGE_HOURS)
    return posted_at >= cutoff


# ──────────────────────────────────────────
# 게시글 목록 수집 (v2.1: 날짜 파싱 추가)
# ──────────────────────────────────────────
async def collect_recent_posts(page: Page) -> list[PostInfo]:
    """
    전체글 보기에서 최신 게시글 수집 후 24시간 이내만 반환
    """
    posts: list[PostInfo] = []

    try:
        await page.goto(CAFE_URL, timeout=20000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

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

                # 작성자 추출
                try:
                    author_el = link.locator("xpath=../..//td[@class='td_name']").first
                    author = (await author_el.text_content() or "알수없음").strip()
                except Exception:
                    author = "알수없음"

                # v2.1: 게시 날짜 추출
                posted_at = None
                try:
                    date_el = link.locator("xpath=../..//td[@class='td_date']").first
                    date_text = await date_el.text_content(timeout=2000) or ""
                    posted_at = _parse_post_date(date_text)
                except Exception:
                    pass  # 날짜 파싱 실패 → None (24시간 필터에서 포함 처리)

                posts.append(PostInfo(
                    url=url,
                    title=title,
                    author=author,
                    posted_at=posted_at,
                ))

            except Exception as e:
                logger.debug(f"[monitor] 게시글 링크 파싱 실패: {e}")
                continue

        # ── 24시간 이내 필터링 (v2.1 핵심) ──
        before_filter = len(posts)
        posts = [p for p in posts if _is_within_24h(p.posted_at)]
        skipped = before_filter - len(posts)

        logger.info(
            f"[monitor] 게시글 수집 완료 | "
            f"전체:{before_filter} 24h이내:{len(posts)} 스킵:{skipped}"
        )

    except Exception as e:
        logger.error(f"[monitor] 게시글 목록 수집 실패: {e}")

    return posts


# ──────────────────────────────────────────
# 댓글 수집
# ──────────────────────────────────────────
async def collect_comments(page: Page, post: PostInfo) -> list[CommentInfo]:
    """
    게시글 페이지에서 댓글 목록 수집
    v2.0: goto 이후 반드시 새 frame 획득
    """
    comments: list[CommentInfo] = []

    try:
        await page.goto(post.url, timeout=20000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_fresh_frame(page)

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
        frame = await _get_fresh_frame(page)

        delete_btn = frame.locator(comment.delete_btn_selector).first
        if not await delete_btn.is_visible(timeout=5000):
            logger.warning(f"[monitor] 삭제 버튼 없음: {comment.author}")
            return False

        await delete_btn.click()
        await asyncio.sleep(0.8)

        try:
            page.once("dialog", lambda d: asyncio.create_task(d.accept()))
        except Exception:
            pass

        await asyncio.sleep(random.uniform(1.0, 2.0))
        logger.info(f"[monitor] 스팸 삭제: {comment.author} — '{comment.content[:30]}'")
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
    v2.1: 24시간 이내 게시글만 처리
    """
    result = MonitorResult()

    posts = await collect_recent_posts(page)
    if not posts:
        logger.info("[monitor] 처리할 게시글 없음 (24시간 이내 신규 없음)")
        return result

    for post in posts:
        result.posts_checked += 1

        try:
            comments = await collect_comments(page, post)
            post.comments = comments

            for comment in comments:
                try:
                    spam_flag, reason = is_spam(
                        comment_text=comment.content,
                        post_context=post.title,
                        comment_author=comment.author,
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
