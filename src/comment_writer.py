"""
comment_writer.py
신규 게시글에 환영 댓글 자동 작성
- Gemini AI로 게시글 내용에 맞는 개인화된 환영 댓글 생성
- 중복 댓글 방지 (processed_posts 테이블 확인)
"""

import os
import json
import random
import asyncio
import re
import google.generativeai as genai
from typing import Optional
from playwright.async_api import Page


class CommentWriter:
    def __init__(self, page: Page):
        self.page = page
        self.cafe_id = os.environ.get("CAFE_ID", "alexstock")

        # Gemini API 설정
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        self.model = genai.GenerativeModel("gemini-1.5-flash")

        # 환영 메시지 템플릿 로드
        keywords_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "keywords.json"
        )
        with open(keywords_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.welcome_templates = config.get("welcome_templates", [])

    async def _random_delay(self, min_sec: float = 3.0, max_sec: float = 8.0):
        """사람처럼 보이기 위한 랜덤 딜레이"""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def generate_welcome_message(
        self, post_title: str, post_content: str = ""
    ) -> str:
        """
        Gemini AI로 게시글에 맞는 개인화된 환영 댓글 생성
        """
        try:
            prompt = f"""당신은 '알렉스강의 주식이야기' 카페 매니저입니다.
카페 철학: "주식을 이야기하지만, 사람을 먼저 생각합니다"

아래 게시글에 어울리는 따뜻하고 친근한 환영/응원 댓글을 작성해주세요.

[게시글 제목]
{post_title}

[게시글 내용 일부]
{post_content[:200] if post_content else "내용 없음"}

[작성 규칙]
- 2~3문장 이내로 짧게
- 이모지 1~2개 사용
- 투자/주식 관련 격려 포함
- 자연스러운 한국어
- 광고나 홍보 내용 절대 없음
- 게시글 내용을 반영한 개인화된 댓글

댓글만 반환하고 다른 설명은 없이:"""

            response = self.model.generate_content(prompt)
            message = response.text.strip()

            # 따옴표 제거
            message = message.strip('"\'')

            print(f"[COMMENT] AI 생성 메시지: {message[:50]}...")
            return message

        except Exception as e:
            print(f"[COMMENT] AI 생성 오류: {e}, 템플릿 사용")
            # AI 오류 시 랜덤 템플릿 사용
            return random.choice(self.welcome_templates)

    async def write_comment(self, post_url: str, message: str) -> bool:
        """
        게시글에 댓글 작성
        """
        try:
            await self.page.goto(post_url, wait_until="networkidle", timeout=30000)
            await self._random_delay(3, 5)

            # iframe 접근
            frame = None
            for f in self.page.frames:
                if self.cafe_id in f.url and "Article" in f.url:
                    frame = f
                    break

            target = frame if frame else self.page

            # 댓글 입력창 찾기 (여러 선택자 시도)
            comment_selectors = [
                "#cafe_comment_input",
                ".comment_write textarea",
                ".cmt_write textarea",
                "textarea[placeholder*='댓글']",
                "#comment",
            ]

            comment_input = None
            for selector in comment_selectors:
                try:
                    comment_input = await target.wait_for_selector(
                        selector, timeout=5000
                    )
                    if comment_input:
                        break
                except Exception:
                    continue

            if not comment_input:
                print(f"[COMMENT] ⚠️ 댓글 입력창을 찾지 못함")
                return False

            # 댓글 입력창 클릭 후 내용 입력
            await comment_input.click()
            await self._random_delay(0.5, 1.5)
            await comment_input.type(message, delay=50)
            await self._random_delay(1, 2)

            # 등록 버튼 클릭
            submit_selectors = [
                ".btn_register",
                ".comment_write .btn_submit",
                "button[type='submit']",
                ".cmt_submit",
            ]

            for selector in submit_selectors:
                try:
                    submit_btn = await target.query_selector(selector)
                    if submit_btn:
                        await submit_btn.click()
                        await self._random_delay(2, 3)
                        print(f"[COMMENT] ✅ 댓글 작성 성공!")
                        return True
                except Exception:
                    continue

            print(f"[COMMENT] ⚠️ 등록 버튼을 찾지 못함")
            return False

        except Exception as e:
            print(f"[COMMENT] 댓글 작성 오류: {e}")
            return False

    async def process_new_post(
        self,
        post: dict,
        processed_urls: set,
    ) -> Optional[str]:
        """
        신규 게시글에 환영 댓글 처리
        Returns: 작성된 메시지 or None
        """
        post_url = post.get("url", "")
        post_title = post.get("title", "")
        post_author = post.get("author", "")

        # 이미 처리된 게시글 건너뜀
        if post_url in processed_urls:
            print(f"[COMMENT] 이미 처리됨: {post_title[:30]}...")
            return None

        # 관리자 본인 게시글은 건너뜀
        if post_author in ["AlexKang", "알렉스", "alexkang"]:
            print(f"[COMMENT] 관리자 게시글 건너뜀: {post_title[:30]}...")
            return None

        print(f"[COMMENT] 새 게시글 처리: {post_title[:40]}...")

        # 환영 메시지 생성
        message = await self.generate_welcome_message(post_title)

        # 댓글 작성
        success = await self.write_comment(post_url, message)

        if success:
            return message
        return None
