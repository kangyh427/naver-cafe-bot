# ============================================================
# 파일명: cafe_monitor.py
# 경로:   kangyh427/naver_cafe_bot/src/cafe_monitor.py
# 역할:   네이버 카페 게시글/댓글 수집 + 스팸 댓글 삭제
#
# 작성일: 2026-03-09
# 수정일: 2026-03-12
# 버전:   v4.0
#
# [v4.0 — 2026-03-12] 댓글 24시간 필터 추가
#   문제: 게시글당 모든 댓글을 Gemini로 판별 → 429 할당량 초과 반복
#   수정:
#     - CommentInfo에 commented_at 필드 추가
#     - collect_comments()에서 댓글 작성 날짜 파싱
#     - 24시간 이내 댓글만 스팸 판별 대상으로 수집
#     - 오래된 댓글은 이미 검토됐다고 판단, 스킵
#   효과: Gemini 호출 횟수 대폭 감소 → 429 오류 원천 차단
#
# [v3.0 — 2026-03-11] 근본 재설계 (selector 확장, URL 정규화)
# [v2.1 — 2026-03-10] 게시글 24h 필터 도입
# [v1.0 — 2026-03-09] 최초 작성
# ============================================================

import os
import asyncio
import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from playwright.async_api import Page

from spam_detector import is_spam
from supabase_logger import log_spam_deleted, is_post_processed

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
CAFE_URL           = os.environ.get("CAFE_URL", "https://cafe.naver.com/alexstock")
CAFE_ID            = os.environ.get("CAFE_ID", "alexstock")
POSTS_TO_MONITOR   = 30
PAGE_LOAD_WAIT_S   = 3.5
ACTION_DELAY_S     = 1.5
POST_MAX_AGE_HOURS = 24

# 네이버 카페 게시글 목록 selector 후보
POST_LINK_SELECTORS = [
    "a.article",
    ".article-board a[href*='ArticleRead']",
    "td.td_article a[href*='ArticleRead']",
    ".board-list a[href*='ArticleRead']",
    "a[href*='ArticleRead']",
]

# 작성자 selector 후보
AUTHOR_SELECTORS = [
    "td.td_name .m-tcol-c",
    "td.td_name",
    ".td_name .m-tcol-c",
    ".td_name",
]

# 날짜 selector 후보 (게시글 목록)
DATE_SELECTORS = [
    "td.td_date",
    ".td_date",
    "td[class*='date']",
]

# 댓글 날짜 selector 후보 (v4.0 추가)
COMMENT_DATE_SELECTORS = [
    ".comment_info_date",
    ".comment_date",
    ".date",
    "span[class*='date']",
    "em.date",
]


# ──────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────
@dataclass
class CommentInfo:
    comment_id:          str
    author:              str
    content:             str
    commented_at:        Optional[datetime] = None   # v4.0 추가
    delete_btn_selector: Optional[str] = None

@dataclass
class PostInfo:
    url:       str
    title:     str
    author:    str
    posted_at: Optional[datetime] = None
    is_new:    bool = False
    comments:  list[CommentInfo] = field(default_factory=list)

@dataclass
class MonitorResult:
    posts_checked: int = 0
    spam_deleted:  int = 0
    errors:        int = 0
    new_post_urls: list[str] = field(default_factory=list)


# ──────────────────────────────────────────
# iframe 안전 획득
# ──────────────────────────────────────────
async def _get_fresh_frame(page: Page):
    """
    페이지 로드 완료 후 항상 새 frame 참조 획득
    안전장치: iframe 없으면 page 직접 반환
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        frame = page.frame_locator("iframe#cafe_main").first
        return frame
    except Exception:
        logger.debug("[monitor] iframe 없음 → page 직접 사용")
        return page


# ──────────────────────────────────────────
# URL 정규화
# ──────────────────────────────────────────
def _normalize_cafe_url(href: str, base_url: str = "https://cafe.naver.com") -> Optional[str]:
    """
    네이버 카페 게시글 URL 정규화
    - 상대경로 → 절대경로
    - 쿼리스트링 포함 ArticleRead URL 처리
    - iframe 파라미터 제거
    """
    if not href:
        return None
    if href.startswith("javascript:") or href == "#":
        return None

    if href.startswith("http"):
        full_url = href
    elif href.startswith("/"):
        full_url = f"https://cafe.naver.com{href}"
    else:
        full_url = urljoin(base_url, href)

    if "ArticleRead" not in full_url:
        return None

    parsed = urlparse(full_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("iframe", None)
    params.pop("referrerAllArticles", None)

    clean_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=clean_query))


# ──────────────────────────────────────────
# 날짜 파싱 (게시글 & 댓글 공용)
# ──────────────────────────────────────────
def _parse_post_date(date_text: str) -> Optional[datetime]:
    """
    네이버 날짜 텍스트 → datetime 변환
    지원 형식:
      "2026.03.10."  → 해당 날짜
      "03.10."       → 올해 해당 날짜
      "10:59"        → 오늘
    안전장치: 파싱 실패 시 None → 호출부에서 포함(True) 처리
    """
    now  = datetime.now(timezone.utc)
    text = date_text.strip().rstrip('.')

    try:
        parts = text.split('.')
        if len(parts) >= 3:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            return datetime(year, month, day, tzinfo=timezone.utc)
        if len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
            return datetime(now.year, month, day, tzinfo=timezone.utc)
        if ':' in text:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, IndexError):
        pass

    return None


def _parse_comment_date(date_text: str) -> Optional[datetime]:
    """
    댓글 날짜 파싱 (v4.0 신규)
    네이버 댓글 날짜 형식:
      "2026.03.12. 14:38"  → datetime
      "03.12. 10:30"       → 올해 datetime
      "10:38"              → 오늘
    안전장치: 파싱 실패 시 None → 24h 이내로 간주 (스팸 판별 누락 방지)
    """
    now  = datetime.now(timezone.utc)
    text = date_text.strip()

    try:
        # "2026.03.12. 14:38" 형식
        if '.' in text and ':' in text:
            date_part, time_part = text.rsplit(' ', 1)
            date_part = date_part.strip().rstrip('.')
            parts = date_part.split('.')
            hour, minute = map(int, time_part.split(':'))

            if len(parts) >= 3:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            elif len(parts) == 2:
                year, month, day = now.year, int(parts[0]), int(parts[1])
            else:
                return None

            return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

        # "10:38" 형식 (오늘)
        if ':' in text and '.' not in text:
            hour, minute = map(int, text.split(':'))
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 날짜만 있는 경우 → _parse_post_date 재사용
        return _parse_post_date(text)

    except (ValueError, IndexError, AttributeError):
        pass

    return None


def _is_within_24h(dt: Optional[datetime]) -> bool:
    """
    24시간 이내인지 확인
    안전장치: None → True (누락 방지 우선)
    """
    if dt is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=POST_MAX_AGE_HOURS)
    return dt >= cutoff


# ──────────────────────────────────────────
# 게시글 목록 수집
# ──────────────────────────────────────────
async def collect_recent_posts(page: Page) -> list[PostInfo]:
    """
    전체글 보기에서 최신 게시글 수집 후 24시간 이내만 반환
    """
    posts: list[PostInfo] = []

    try:
        await page.goto(CAFE_URL, timeout=25000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_fresh_frame(page)

        # 게시글 링크 수집
        post_links = []
        for selector in POST_LINK_SELECTORS:
            try:
                links = await frame.locator(selector).all()
                if links:
                    post_links = links
                    logger.info(f"[monitor] 게시글 링크 selector 성공: '{selector}' → {len(links)}개")
                    break
            except Exception as e:
                logger.debug(f"[monitor] selector 실패 '{selector}': {e}")
                continue

        if not post_links:
            logger.error("[monitor] 게시글 링크를 찾을 수 없음 — 모든 selector 실패")
            try:
                body_text = await page.locator("body").text_content(timeout=3000)
                logger.debug(f"[monitor] 페이지 body 앞부분: {body_text[:300] if body_text else '없음'}")
            except Exception:
                pass
            return posts

        # 각 링크에서 URL/제목/작성자/날짜 추출
        for link in post_links[:POSTS_TO_MONITOR]:
            try:
                href  = await link.get_attribute("href") or ""
                title = (await link.text_content() or "제목없음").strip()
                title = title.replace("\n", " ").strip()

                url = _normalize_cafe_url(href)
                if not url:
                    logger.debug(f"[monitor] URL 정규화 실패, 스킵: href='{href[:80]}'")
                    continue

                author = "알수없음"
                for auth_sel in AUTHOR_SELECTORS:
                    try:
                        parent_row  = link.locator("xpath=ancestor::tr[1]")
                        author_text = await parent_row.locator(auth_sel).first.text_content(timeout=2000)
                        if author_text and author_text.strip():
                            author = author_text.strip()
                            break
                    except Exception:
                        continue

                posted_at = None
                for date_sel in DATE_SELECTORS:
                    try:
                        parent_row = link.locator("xpath=ancestor::tr[1]")
                        date_text  = await parent_row.locator(date_sel).first.text_content(timeout=2000)
                        if date_text and date_text.strip():
                            posted_at = _parse_post_date(date_text.strip())
                            break
                    except Exception:
                        continue

                posts.append(PostInfo(url=url, title=title, author=author, posted_at=posted_at))
                logger.debug(f"[monitor] 게시글 수집: '{title[:30]}' | {author}")

            except Exception as e:
                logger.debug(f"[monitor] 게시글 링크 파싱 실패: {e}")
                continue

        # 24시간 이내 필터링
        before_filter = len(posts)
        posts = [p for p in posts if _is_within_24h(p.posted_at)]
        skipped = before_filter - len(posts)

        logger.info(
            f"[monitor] 게시글 수집 완료 | "
            f"전체:{before_filter} 24h이내:{len(posts)} 날짜필터스킵:{skipped}"
        )

    except Exception as e:
        logger.error(f"[monitor] 게시글 목록 수집 실패: {e}", exc_info=True)

    return posts


# ──────────────────────────────────────────
# 댓글 수집 (v4.0: 24h 필터 추가)
# ──────────────────────────────────────────
async def collect_comments(page: Page, post: PostInfo) -> list[CommentInfo]:
    """
    게시글 페이지에서 댓글 수집
    v4.0: 24시간 이내 댓글만 반환 → Gemini 호출 최소화
    """
    comments: list[CommentInfo] = []

    COMMENT_ITEM_SELECTORS    = [".comment_list li.CommentItem", ".comment-list li", ".CommentBox li"]
    COMMENT_AUTHOR_SELECTORS  = [".comment_nickname .nick", ".comment_nickname", ".nick", ".m-tcol-c"]
    COMMENT_CONTENT_SELECTORS = [".comment_text_box .comment_text", ".comment_text_box", ".comment_body", ".comment_text"]

    try:
        await page.goto(post.url, timeout=25000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_fresh_frame(page)

        comment_items = []
        for sel in COMMENT_ITEM_SELECTORS:
            try:
                items = await frame.locator(sel).all()
                if items:
                    comment_items = items
                    logger.debug(f"[monitor] 댓글 selector 성공: '{sel}' → {len(items)}개")
                    break
            except Exception:
                continue

        if not comment_items:
            logger.debug(f"[monitor] 댓글 없음: {post.url[-50:]}")
            return comments

        total_comments   = len(comment_items)
        skipped_old      = 0

        for idx, item in enumerate(comment_items):
            try:
                comment_id = await item.get_attribute("data-comment-id") or f"idx_{idx}"

                # ── 댓글 날짜 추출 (v4.0 신규) ──
                commented_at = None
                for date_sel in COMMENT_DATE_SELECTORS:
                    try:
                        date_text = await item.locator(date_sel).first.text_content(timeout=2000)
                        if date_text and date_text.strip():
                            commented_at = _parse_comment_date(date_text.strip())
                            break
                    except Exception:
                        continue

                # ── 24시간 이내 댓글만 처리 ──
                if not _is_within_24h(commented_at):
                    skipped_old += 1
                    continue

                # 작성자 추출
                author = "알수없음"
                for auth_sel in COMMENT_AUTHOR_SELECTORS:
                    try:
                        text = await item.locator(auth_sel).first.text_content(timeout=2000)
                        if text and text.strip():
                            author = text.strip()
                            break
                    except Exception:
                        continue

                # 내용 추출
                content = ""
                for cont_sel in COMMENT_CONTENT_SELECTORS:
                    try:
                        text = await item.locator(cont_sel).first.text_content(timeout=2000)
                        if text and text.strip():
                            content = text.strip()
                            break
                    except Exception:
                        continue

                if not content:
                    continue

                delete_selector = (
                    f"li.CommentItem:nth-child({idx + 1}) .btn_delete, "
                    f"li.CommentItem:nth-child({idx + 1}) .comment_delete"
                )

                comments.append(CommentInfo(
                    comment_id=comment_id,
                    author=author,
                    content=content,
                    commented_at=commented_at,
                    delete_btn_selector=delete_selector,
                ))

            except Exception as e:
                logger.debug(f"[monitor] 댓글 파싱 실패 (idx:{idx}): {e}")
                continue

        logger.debug(
            f"[monitor] 댓글 수집 완료 | "
            f"전체:{total_comments} 24h이내:{len(comments)} 오래된댓글스킵:{skipped_old} "
            f"— '{post.title[:25]}'"
        )

    except Exception as e:
        logger.error(f"[monitor] 댓글 수집 실패 [{post.url[:50]}]: {e}")

    return comments


# ──────────────────────────────────────────
# 스팸 댓글 삭제
# ──────────────────────────────────────────
async def delete_spam_comment(page: Page, post: PostInfo, comment: CommentInfo) -> bool:
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
        logger.info(f"[monitor] 스팸 삭제 완료: {comment.author} — '{comment.content[:30]}'")
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

    v4.0:
      - collect_comments()가 24h 이내 댓글만 반환
      - Gemini 호출 횟수 대폭 감소
    """
    result = MonitorResult()

    posts = await collect_recent_posts(page)
    if not posts:
        logger.info("[monitor] 처리할 게시글 없음 (24시간 이내 신규 없음)")
        return result

    logger.info(f"[monitor] {len(posts)}개 게시글 처리 시작")

    for post in posts:
        result.posts_checked += 1
        logger.debug(f"[monitor] 처리 중 ({result.posts_checked}/{len(posts)}): '{post.title[:30]}'")

        try:
            # 댓글 수집 (24h 이내만)
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

            # 환영 댓글 대상 판단
            if not is_post_processed(post.url):
                result.new_post_urls.append(post.url)
                logger.debug(f"[monitor] 신규 게시글 등록: {post.author} — '{post.title[:30]}'")
            else:
                logger.debug(f"[monitor] 이미 처리된 게시글 스킵: {post.url[-50:]}")

            await asyncio.sleep(random.uniform(ACTION_DELAY_S, ACTION_DELAY_S + 1.5))

        except Exception as e:
            logger.error(f"[monitor] 게시글 처리 오류 [{post.url[:50]}]: {e}")
            result.errors += 1

    logger.info(
        f"[monitor] 완료 | "
        f"게시글:{result.posts_checked} 스팸삭제:{result.spam_deleted} "
        f"신규(환영대상):{len(result.new_post_urls)} 오류:{result.errors}"
    )
    return result
