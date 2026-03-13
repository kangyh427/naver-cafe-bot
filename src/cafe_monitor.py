# ============================================================
# 파일명: cafe_monitor.py
# 경로:   kangyh427/naver-cafe-bot/src/cafe_monitor.py
# 역할:   네이버 카페 게시글/댓글 수집 + 스팸/사칭 댓글 삭제
#
# 작성일: 2026-03-09
# 수정일: 2026-03-13
# 버전:   v5.0
#
# [v5.0 — 2026-03-13] 삭제 로직 근본 재설계
#   버그 수정 1: dialog 핸들러를 클릭 후에 등록하던 치명적 오류 수정
#               → 클릭 전 등록으로 변경 (확인 대화창 놓치던 문제 해결)
#   버그 수정 2: FrameLocator 방식 → page.frames Frame 객체 방식으로 통일
#               comment_dom.py와 동일한 Frame 접근 방식 사용
#   버그 수정 3: 댓글 삭제 시 data-comment-id 기반 selector 우선 사용
#               → nth-child 방식보다 신뢰성 대폭 향상
#   개선: 삭제 버튼 selector 다수 추가 (네이버 카페 다양한 DOM 대응)
#   개선: 재탐색 로직 추가 (삭제 전 해당 게시글 페이지 위치 확인)
#
# [v4.0 — 2026-03-12] 댓글 24시간 필터 추가
# [v3.0 — 2026-03-11] 근본 재설계 (selector 확장, URL 정규화)
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

# 게시글 목록 selector 후보
POST_LINK_SELECTORS = [
    "a.article",
    ".article-board a[href*='ArticleRead']",
    "td.td_article a[href*='ArticleRead']",
    ".board-list a[href*='ArticleRead']",
    "a[href*='ArticleRead']",
]

AUTHOR_SELECTORS = [
    "td.td_name .m-tcol-c",
    "td.td_name",
    ".td_name .m-tcol-c",
    ".td_name",
]

DATE_SELECTORS = [
    "td.td_date",
    ".td_date",
    "td[class*='date']",
]

COMMENT_DATE_SELECTORS = [
    ".comment_info_date",
    ".comment_date",
    ".date",
    "span[class*='date']",
    "em.date",
]

# v5.0: 삭제 버튼 selector 목록 (우선순위 순)
DELETE_BTN_SELECTORS = [
    ".btn_delete",
    ".comment_delete",
    ".ico_delete",
    ".u_cbox_btn_delete",
    "button[class*='delete']",
    "a[class*='delete']",
    ".comment_option .delete",
    ".opt_comment .delete",
]


# ──────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────
@dataclass
class CommentInfo:
    comment_id:   str
    author:       str
    content:      str
    commented_at: Optional[datetime] = None
    item_index:   int = 0           # v5.0: nth-child 계산용 (0-based)

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
# v5.0: Frame 객체 획득 (comment_dom.py와 동일 방식으로 통일)
# ──────────────────────────────────────────
async def _get_frame_object(page: Page):
    """
    cafe_main iframe의 실제 Frame 객체 획득
    FrameLocator(액션 불가)가 아닌 Frame 객체 반환

    순서: iframe 대기 → URL 매칭 → name 매칭 → page 폴백
    안전장치: 최대 3회 재시도 (iframe 로딩 지연 대응)
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # iframe이 DOM에 나타날 때까지 최대 5초 대기
        try:
            await page.wait_for_selector("iframe#cafe_main", timeout=5000)
        except Exception:
            pass

        # 1차: URL 기반 탐색 (가장 신뢰, 최대 3회 재시도)
        for attempt in range(3):
            for frame in page.frames:
                if ("cafe.naver.com" in frame.url or
                    "ca-fe.naver.com" in frame.url or
                    "ArticleRead" in frame.url):
                    logger.debug(f"[monitor] Frame 발견(URL): {frame.url[:60]}")
                    return frame
            if attempt < 2:
                await asyncio.sleep(1.0)

        # 2차: name 기반
        named_frame = page.frame(name="cafe_main")
        if named_frame:
            logger.debug("[monitor] Frame 발견(name=cafe_main)")
            return named_frame

        # 3차: 폴백 — page 직접 사용
        logger.debug(
            f"[monitor] iframe 미발견 → page 직접 사용 "
            f"(총 {len(page.frames)}개 frame)"
        )
        return page

    except Exception as e:
        logger.debug(f"[monitor] Frame 획득 예외 → page 폴백: {e}")
        return page


# ──────────────────────────────────────────
# URL 정규화
# ──────────────────────────────────────────
def _normalize_cafe_url(href: str, base_url: str = "https://cafe.naver.com") -> Optional[str]:
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
# 날짜 파싱
# ──────────────────────────────────────────
def _parse_post_date(date_text: str) -> Optional[datetime]:
    now  = datetime.now(timezone.utc)
    text = date_text.strip().rstrip('.')
    try:
        parts = text.split('.')
        if len(parts) >= 3:
            return datetime(int(parts[0]), int(parts[1]), int(parts[2]), tzinfo=timezone.utc)
        if len(parts) == 2:
            return datetime(now.year, int(parts[0]), int(parts[1]), tzinfo=timezone.utc)
        if ':' in text:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, IndexError):
        pass
    return None


def _parse_comment_date(date_text: str) -> Optional[datetime]:
    now  = datetime.now(timezone.utc)
    text = date_text.strip()
    try:
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
        if ':' in text and '.' not in text:
            hour, minute = map(int, text.split(':'))
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return _parse_post_date(text)
    except (ValueError, IndexError, AttributeError):
        pass
    return None


def _is_within_24h(dt: Optional[datetime]) -> bool:
    if dt is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=POST_MAX_AGE_HOURS)
    return dt >= cutoff


# ──────────────────────────────────────────
# 게시글 목록 수집
# ──────────────────────────────────────────
async def collect_recent_posts(page: Page) -> list[PostInfo]:
    posts: list[PostInfo] = []
    try:
        await page.goto(CAFE_URL, timeout=25000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_frame_object(page)

        post_links = []
        for selector in POST_LINK_SELECTORS:
            try:
                links = await frame.locator(selector).all()
                if links:
                    post_links = links
                    logger.info(f"[monitor] 게시글 selector 성공: '{selector}' → {len(links)}개")
                    break
            except Exception as e:
                logger.debug(f"[monitor] selector 실패 '{selector}': {e}")
                continue

        if not post_links:
            logger.error("[monitor] 게시글 링크를 찾을 수 없음 — 모든 selector 실패")
            return posts

        for link in post_links[:POSTS_TO_MONITOR]:
            try:
                href  = await link.get_attribute("href") or ""
                title = (await link.text_content() or "제목없음").strip().replace("\n", " ")
                url   = _normalize_cafe_url(href)
                if not url:
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

            except Exception as e:
                logger.debug(f"[monitor] 게시글 파싱 실패: {e}")
                continue

        before_filter = len(posts)
        posts = [p for p in posts if _is_within_24h(p.posted_at)]
        logger.info(
            f"[monitor] 게시글 수집 완료 | "
            f"전체:{before_filter} 24h이내:{len(posts)} 스킵:{before_filter - len(posts)}"
        )

    except Exception as e:
        logger.error(f"[monitor] 게시글 목록 수집 실패: {e}", exc_info=True)

    return posts


# ──────────────────────────────────────────
# 댓글 수집
# ──────────────────────────────────────────
async def collect_comments(page: Page, post: PostInfo) -> list[CommentInfo]:
    """
    게시글 댓글 수집 (24h 이내만)
    v5.0: item_index 저장으로 삭제 시 정확한 위치 파악
    """
    comments: list[CommentInfo] = []

    COMMENT_ITEM_SELECTORS = [
        ".comment_list li.CommentItem",
        ".comment-list li",
        ".CommentBox li",
        "li.CommentItem",
    ]
    COMMENT_AUTHOR_SELECTORS = [
        ".comment_nickname .nick",
        ".comment_nickname",
        ".nick",
        ".m-tcol-c",
    ]
    COMMENT_CONTENT_SELECTORS = [
        ".comment_text_box .comment_text",
        ".comment_text_box",
        ".comment_body",
        ".comment_text",
    ]

    try:
        await page.goto(post.url, timeout=25000, wait_until="domcontentloaded")
        await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_frame_object(page)

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

        total_comments = len(comment_items)
        skipped_old   = 0

        for idx, item in enumerate(comment_items):
            try:
                # data-comment-id 우선, 없으면 data-id, 최후에 idx_N
                comment_id = (
                    await item.get_attribute("data-comment-id") or
                    await item.get_attribute("data-id") or
                    f"idx_{idx}"
                )

                # 댓글 날짜 추출
                commented_at = None
                for date_sel in COMMENT_DATE_SELECTORS:
                    try:
                        date_text = await item.locator(date_sel).first.text_content(timeout=2000)
                        if date_text and date_text.strip():
                            commented_at = _parse_comment_date(date_text.strip())
                            break
                    except Exception:
                        continue

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

                comments.append(CommentInfo(
                    comment_id=comment_id,
                    author=author,
                    content=content,
                    commented_at=commented_at,
                    item_index=idx,
                ))

            except Exception as e:
                logger.debug(f"[monitor] 댓글 파싱 실패 (idx:{idx}): {e}")
                continue

        logger.debug(
            f"[monitor] 댓글 수집 | "
            f"전체:{total_comments} 24h이내:{len(comments)} 오래된:{skipped_old} "
            f"— '{post.title[:25]}'"
        )

    except Exception as e:
        logger.error(f"[monitor] 댓글 수집 실패 [{post.url[:50]}]: {e}")

    return comments


# ──────────────────────────────────────────
# 스팸/사칭 댓글 삭제 (v5.0 핵심 수정)
# ──────────────────────────────────────────
async def delete_spam_comment(page: Page, post: PostInfo, comment: CommentInfo) -> bool:
    """
    스팸/사칭 댓글 관리자 삭제

    v5.0 핵심 수정:
      [버그수정] dialog 핸들러 → 클릭 전 등록 (기존: 클릭 후 등록)
      [버그수정] FrameLocator → Frame 객체 방식으로 통일
      [개선] data-comment-id 기반 정확한 버튼 탐색 (1순위)
      [개선] nth-child 기반 탐색 (2순위, item_index 활용)
      [개선] 게시글 페이지 위치 확인 후 필요 시 재이동
    """
    try:
        # 현재 페이지가 대상 게시글인지 확인 후 필요 시 재이동
        current_url = page.url
        if post.url not in current_url and current_url not in post.url:
            logger.debug(f"[monitor] 게시글 재이동: {post.url[-60:]}")
            await page.goto(post.url, timeout=25000, wait_until="domcontentloaded")
            await asyncio.sleep(PAGE_LOAD_WAIT_S)

        frame = await _get_frame_object(page)

        # ── 삭제 버튼 탐색: 전략 1 — data-comment-id ──
        delete_btn = None

        if comment.comment_id and not comment.comment_id.startswith("idx_"):
            id_selectors = [
                f"[data-comment-id='{comment.comment_id}'] .btn_delete",
                f"[data-comment-id='{comment.comment_id}'] .comment_delete",
                f"[data-id='{comment.comment_id}'] .btn_delete",
                f"li[data-comment-id='{comment.comment_id}'] button[class*='delete']",
                f"li[data-comment-id='{comment.comment_id}'] a[class*='delete']",
            ]
            for sel in id_selectors:
                try:
                    btn = frame.locator(sel).first
                    if await btn.is_visible(timeout=3000):
                        delete_btn = btn
                        logger.debug(f"[monitor] 삭제버튼 발견(comment-id): '{sel}'")
                        break
                except Exception:
                    continue

        # ── 삭제 버튼 탐색: 전략 2 — nth-child (item_index 활용) ──
        if delete_btn is None:
            nth = comment.item_index + 1
            ITEM_PARENT_SELECTORS = [
                "li.CommentItem",
                ".comment_list li",
                ".CommentBox li",
            ]
            for item_sel in ITEM_PARENT_SELECTORS:
                for del_sel in DELETE_BTN_SELECTORS:
                    try:
                        full_sel = f"{item_sel}:nth-child({nth}) {del_sel}"
                        btn = frame.locator(full_sel).first
                        if await btn.is_visible(timeout=2000):
                            delete_btn = btn
                            logger.debug(f"[monitor] 삭제버튼 발견(nth): '{full_sel}'")
                            break
                    except Exception:
                        continue
                if delete_btn:
                    break

        if delete_btn is None:
            logger.warning(
                f"[monitor] 삭제 버튼 미발견: '{comment.author}' "
                f"(관리자 권한 확인 필요 또는 selector 불일치)"
            )
            return False

        # ── [v5.0 핵심 수정] dialog 핸들러를 클릭 전에 등록 ──
        async def _handle_dialog(dialog):
            logger.debug(f"[monitor] 삭제 확인 다이얼로그 수락: '{dialog.message[:50]}'")
            await dialog.accept()

        page.once("dialog", _handle_dialog)   # ← 반드시 클릭 전에 등록

        await delete_btn.click()
        await asyncio.sleep(2.0)              # 다이얼로그 처리 + 페이지 반영 대기

        logger.info(
            f"[monitor] ✅ 삭제 완료: "
            f"'{comment.author}' — '{comment.content[:40]}'"
        )
        return True

    except Exception as e:
        logger.error(f"[monitor] 댓글 삭제 실패: {e}", exc_info=True)
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
        logger.info("[monitor] 처리할 게시글 없음 (24시간 이내 신규 없음)")
        return result

    logger.info(f"[monitor] {len(posts)}개 게시글 처리 시작")

    for post in posts:
        result.posts_checked += 1
        logger.info(f"[monitor] 처리 중 ({result.posts_checked}/{len(posts)}): '{post.title[:30]}'")

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
                        logger.info(
                            f"[monitor] 감지: '{comment.author}' | 사유: {reason}"
                        )
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
                logger.debug(f"[monitor] 환영 대상 등록: '{post.title[:30]}'")
            else:
                logger.debug(f"[monitor] 이미 처리됨 스킵: {post.url[-50:]}")

            await asyncio.sleep(random.uniform(ACTION_DELAY_S, ACTION_DELAY_S + 1.5))

        except Exception as e:
            logger.error(f"[monitor] 게시글 처리 오류 [{post.url[:50]}]: {e}")
            result.errors += 1

    logger.info(
        f"[monitor] 완료 | "
        f"게시글:{result.posts_checked} 스팸삭제:{result.spam_deleted} "
        f"환영대상:{len(result.new_post_urls)} 오류:{result.errors}"
    )
    return result
