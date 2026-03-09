"""
cafe_monitor.py
네이버 카페 게시글 및 댓글 모니터링
- 최신 게시글 목록 수집
- 각 게시글의 댓글 수집
- 신규 게시글 감지
"""

import asyncio
import random
from typing import List, Dict, Optional
from playwright.async_api import Page


class CafeMonitor:
    def __init__(self, page: Page, cafe_id: str = "alexstock"):
        self.page = page
        self.cafe_id = cafe_id
        self.base_url = f"https://cafe.naver.com/{cafe_id}"

    async def _random_delay(self, min_sec: float = 2.0, max_sec: float = 5.0):
        """사람처럼 보이기 위한 랜덤 딜레이"""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def get_recent_posts(self, max_posts: int = 20) -> List[Dict]:
        """
        전체글보기에서 최신 게시글 목록 수집
        Returns: [{"title": str, "url": str, "author": str, "board": str}]
        """
        posts = []
        try:
            print(f"[MONITOR] 최신 게시글 수집 중...")

            # 전체글보기 iframe URL로 직접 접근
            list_url = f"https://cafe.naver.com/ArticleList.nhn?search.clubid=10050201&search.boardtype=L"
            await self.page.goto(list_url, wait_until="networkidle", timeout=30000)
            await self._random_delay(2, 4)

            # iframe 내부 접근
            frame = None
            for f in self.page.frames:
                if "ArticleList" in f.url or "cafe.naver.com" in f.url:
                    frame = f
                    break

            target = frame if frame else self.page

            # 게시글 목록 추출
            articles = await target.query_selector_all(".article-board tbody tr")

            for article in articles[:max_posts]:
                try:
                    # 공지사항 제외
                    notice_badge = await article.query_selector(".ico_notice")
                    if notice_badge:
                        continue

                    # 제목 추출
                    title_el = await article.query_selector(".article")
                    if not title_el:
                        title_el = await article.query_selector("a.article")
                    if not title_el:
                        continue

                    title = await title_el.inner_text()
                    href = await title_el.get_attribute("href")

                    if not href:
                        continue

                    # 완전한 URL 구성
                    if href.startswith("http"):
                        url = href
                    elif href.startswith("/"):
                        url = f"https://cafe.naver.com{href}"
                    else:
                        url = f"https://cafe.naver.com/{href}"

                    # 작성자 추출
                    author_el = await article.query_selector(".td_name .m-tcol-c")
                    author = await author_el.inner_text() if author_el else "알 수 없음"

                    # 게시판명 추출
                    board_el = await article.query_selector(".td_article a")
                    board = await board_el.inner_text() if board_el else "기타"

                    posts.append({
                        "title": title.strip(),
                        "url": url.strip(),
                        "author": author.strip(),
                        "board": board.strip(),
                    })

                except Exception as e:
                    continue

            print(f"[MONITOR] 게시글 {len(posts)}개 수집 완료")
            return posts

        except Exception as e:
            print(f"[MONITOR] 게시글 수집 오류: {e}")
            return []

    async def get_comments_from_post(self, post_url: str) -> List[Dict]:
        """
        특정 게시글의 댓글 목록 수집
        Returns: [{"id": str, "author": str, "content": str, "delete_selector": str}]
        """
        comments = []
        try:
            await self.page.goto(post_url, wait_until="networkidle", timeout=30000)
            await self._random_delay(2, 3)

            # iframe 내부 댓글 접근
            frame = None
            for f in self.page.frames:
                if "ArticleRead" in f.url or self.cafe_id in f.url:
                    frame = f
                    break

            target = frame if frame else self.page

            # 댓글 요소 수집
            comment_items = await target.query_selector_all(".comment_box .comment_content")
            if not comment_items:
                comment_items = await target.query_selector_all(".cmt_list li")

            for idx, item in enumerate(comment_items):
                try:
                    # 댓글 내용
                    content_el = await item.query_selector(".comment_text_view, .cmt_text")
                    if not content_el:
                        continue
                    content = await content_el.inner_text()

                    # 작성자
                    author_el = await item.query_selector(".comment_nickname, .cmt_writer")
                    author = await author_el.inner_text() if author_el else "알 수 없음"

                    # 댓글 고유 ID (삭제 시 필요)
                    comment_id = await item.get_attribute("data-comment-id") or str(idx)

                    comments.append({
                        "id": comment_id,
                        "author": author.strip(),
                        "content": content.strip(),
                        "post_url": post_url,
                        "index": idx,
                    })

                except Exception:
                    continue

            print(f"[MONITOR] 댓글 {len(comments)}개 수집 (게시글: {post_url[:50]}...)")
            return comments

        except Exception as e:
            print(f"[MONITOR] 댓글 수집 오류: {e}")
            return []

    async def delete_comment(self, post_url: str, comment_index: int) -> bool:
        """
        스팸 댓글 삭제 (관리자 권한 필요)
        """
        try:
            await self.page.goto(post_url, wait_until="networkidle", timeout=30000)
            await self._random_delay(2, 4)

            frame = None
            for f in self.page.frames:
                if self.cafe_id in f.url:
                    frame = f
                    break

            target = frame if frame else self.page

            # 댓글 삭제 버튼 찾기
            delete_btns = await target.query_selector_all(
                ".comment_area .btn_delete, .cmt_delete, button[data-action='delete']"
            )

            if comment_index < len(delete_btns):
                await delete_btns[comment_index].click()
                await self._random_delay(1, 2)

                # 확인 팝업 처리
                try:
                    await self.page.wait_for_selector(
                        ".btn_confirm, .ok_btn", timeout=3000
                    )
                    confirm_btn = await self.page.query_selector(".btn_confirm, .ok_btn")
                    if confirm_btn:
                        await confirm_btn.click()
                        await self._random_delay(1, 2)
                except Exception:
                    pass  # 팝업 없으면 통과

                print(f"[DELETE] ✅ 댓글 삭제 성공 (index: {comment_index})")
                return True

            print(f"[DELETE] ⚠️ 삭제 버튼 찾지 못함")
            return False

        except Exception as e:
            print(f"[DELETE] 댓글 삭제 오류: {e}")
            return False
