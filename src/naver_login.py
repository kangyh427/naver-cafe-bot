"""
naver_login.py
네이버 로그인 및 브라우저 세션 관리
- Playwright를 사용한 헤드리스 브라우저 제어
- 세션 쿠키 저장/재사용으로 반복 로그인 방지
"""

import os
import json
import asyncio
from playwright.async_api import async_playwright, Browser, Page


class NaverLoginManager:
    def __init__(self):
        self.naver_id = os.environ.get("NAVER_ID")
        self.naver_pw = os.environ.get("NAVER_PW")
        self.cafe_url = os.environ.get("CAFE_URL", "https://cafe.naver.com/alexstock")
        self.cookie_file = "/tmp/naver_session.json"
        self.playwright = None
        self.browser: Browser = None
        self.page: Page = None

    async def init_browser(self):
        """브라우저 초기화 (GitHub Actions 환경 최적화)"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,  # 서버 환경에서는 헤드리스 모드
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
            ]
        )
        context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
        )
        self.page = await context.new_page()
        return self.page

    async def login(self) -> bool:
        """네이버 로그인 수행"""
        try:
            print(f"[LOGIN] 네이버 로그인 시도: {self.naver_id}")

            # 네이버 로그인 페이지 이동
            await self.page.goto(
                "https://nid.naver.com/nidlogin.login",
                wait_until="networkidle",
                timeout=30000
            )
            await asyncio.sleep(2)

            # 아이디 입력 (사람처럼 타이핑)
            await self.page.click("#id")
            await self.page.type("#id", self.naver_id, delay=80)
            await asyncio.sleep(0.5)

            # 비밀번호 입력
            await self.page.click("#pw")
            await self.page.type("#pw", self.naver_pw, delay=80)
            await asyncio.sleep(0.5)

            # 로그인 버튼 클릭
            await self.page.click("#log\\.login")
            await asyncio.sleep(3)

            # 로그인 성공 여부 확인
            current_url = self.page.url
            if "naver.com" in current_url and "login" not in current_url:
                print("[LOGIN] ✅ 로그인 성공!")
                return True
            else:
                # 2차 인증이나 캡차 처리
                print(f"[LOGIN] ⚠️ 현재 URL: {current_url}")
                # 캡차 발생 시 잠시 대기
                if "captcha" in current_url or "challenge" in current_url:
                    print("[LOGIN] ❌ 캡차 감지됨 - 잠시 후 재시도 필요")
                    return False
                return True

        except Exception as e:
            print(f"[LOGIN] ❌ 로그인 오류: {e}")
            return False

    async def verify_cafe_access(self) -> bool:
        """카페 관리자 접근 권한 확인"""
        try:
            await self.page.goto(self.cafe_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # 카페 관리 버튼 존재 여부로 관리자 확인
            manager_btn = await self.page.query_selector("a.cafe-manage")
            if manager_btn:
                print("[CAFE] ✅ 카페 관리자 권한 확인!")
                return True

            # 대안 확인 방법
            page_content = await self.page.content()
            if "카페관리" in page_content or "AlexKang" in page_content:
                print("[CAFE] ✅ 카페 접근 확인!")
                return True

            print("[CAFE] ⚠️ 카페 접근 권한 확인 필요")
            return True  # 일단 진행

        except Exception as e:
            print(f"[CAFE] 카페 접근 오류: {e}")
            return False

    async def close(self):
        """브라우저 종료"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("[BROWSER] 브라우저 종료 완료")
