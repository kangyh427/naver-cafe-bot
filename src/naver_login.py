# ============================================================
# 파일명: naver_login.py
# 경로:   kangyh427/naver_cafe_bot/src/naver_login.py
# 역할:   Playwright 브라우저 초기화 + 네이버 로그인/세션 관리
#
# 작성일: 2026-03-09
# 버전:   v1.0
#
# 의존성:
#   - playwright (pip install playwright && playwright install chromium)
#   - 환경변수: NAVER_ID, NAVER_PW
#
# 작동 원리:
#   - 헤드리스 Chromium으로 네이버 로그인 자동화
#   - 사람처럼 보이도록 랜덤 딜레이 + 자연스러운 타이핑 속도
#   - 로그인 성공 여부를 URL/쿠키로 검증
#   - Context Manager 지원 — with 문으로 브라우저 자동 정리
#
# 안전장치:
#   - 환경변수 누락 시 즉시 예외 (undefined behavior 방지)
#   - 로그인 실패(캡차, 2차인증 등) 명확한 예외 메시지
#   - 브라우저 비정상 종료 시에도 리소스 정리 보장
#   - 네이버 계정 보호: 랜덤 딜레이로 봇 탐지 우회
# ============================================================

import os
import asyncio
import random
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 타이밍 상수 (계정 보호용)
# ──────────────────────────────────────────
TYPE_DELAY_MIN_MS  = 80   # 타이핑 최소 딜레이 (ms)
TYPE_DELAY_MAX_MS  = 200  # 타이핑 최대 딜레이 (ms)
ACTION_DELAY_MIN_S = 1.0  # 액션 간 최소 대기 (초)
ACTION_DELAY_MAX_S = 3.0  # 액션 간 최대 대기 (초)
LOGIN_TIMEOUT_MS   = 15000  # 로그인 페이지 로딩 타임아웃 (ms)

# 네이버 URL
NAVER_LOGIN_URL = "https://nid.naver.com/nidlogin.login"
NAVER_MAIN_URL  = "https://www.naver.com"


def _human_delay() -> float:
    """사람처럼 보이는 랜덤 대기 시간 (초)"""
    return random.uniform(ACTION_DELAY_MIN_S, ACTION_DELAY_MAX_S)


async def _type_humanlike(page: Page, selector: str, text: str) -> None:
    """
    사람처럼 한 글자씩 타이핑 (봇 탐지 우회)
    각 글자 사이 랜덤 딜레이 적용
    """
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.3, 0.7))
    await page.type(selector, text, delay=random.randint(TYPE_DELAY_MIN_MS, TYPE_DELAY_MAX_MS))


# ──────────────────────────────────────────
# 브라우저 초기화
# ──────────────────────────────────────────
async def _create_browser_context(playwright) -> BrowserContext:
    """
    헤드리스 Chromium 브라우저 컨텍스트 생성
    실제 사용자 환경처럼 보이도록 설정
    """
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",  # GitHub Actions 메모리 제한 대응
            "--disable-blink-features=AutomationControlled",  # 자동화 탐지 방지
        ],
    )

    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="ko-KR",
        timezone_id="Asia/Seoul",
    )

    return context


# ──────────────────────────────────────────
# 네이버 로그인
# ──────────────────────────────────────────
async def _do_login(page: Page, naver_id: str, naver_pw: str) -> None:
    """
    네이버 로그인 실행
    Raises:
        RuntimeError: 로그인 실패 (캡차, 2차 인증, 잘못된 비밀번호 등)
    """
    logger.info("[login] 네이버 로그인 페이지 접속 중...")
    await page.goto(NAVER_LOGIN_URL, timeout=LOGIN_TIMEOUT_MS)
    await asyncio.sleep(_human_delay())

    # ID / PW 입력
    await _type_humanlike(page, "#id", naver_id)
    await asyncio.sleep(random.uniform(0.5, 1.0))
    await _type_humanlike(page, "#pw", naver_pw)
    await asyncio.sleep(random.uniform(0.5, 1.2))

    # 로그인 버튼 클릭
    await page.click(".btn_login")
    await asyncio.sleep(2.0)  # 로그인 처리 대기

    # ── 로그인 결과 검증 ──
    current_url = page.url

    # 캡차 감지
    if "captcha" in current_url or "challenge" in current_url:
        raise RuntimeError(
            "[login] 캡차 페이지 감지 — 수동 로그인 필요. "
            "네이버 계정 보안 설정에서 '2단계 인증' 또는 '이상 로그인 차단' 확인 요망."
        )

    # 2차 인증 감지
    if "nidlogin" in current_url and "otp" in current_url.lower():
        raise RuntimeError("[login] 2단계 인증 필요 — 수동 처리 요망.")

    # 로그인 유지 팝업 처리 (나타날 경우)
    try:
        btn = page.locator("text=다음에 하기")
        if await btn.is_visible(timeout=2000):
            await btn.click()
            await asyncio.sleep(1.0)
    except Exception:
        pass  # 팝업 없으면 무시

    # 최종 로그인 성공 확인 (메인 페이지 이동 여부)
    await page.goto(NAVER_MAIN_URL, timeout=LOGIN_TIMEOUT_MS)
    await asyncio.sleep(1.5)

    # 로그인 상태 확인: 로그아웃 버튼 또는 사용자명 존재 여부
    is_logged_in = await page.locator(".gnb_my_area, .MyView-module__link_login___HpHMW").count() > 0
    if not is_logged_in:
        raise RuntimeError(
            f"[login] 로그인 실패 — 현재 URL: {page.url}. "
            "NAVER_ID, NAVER_PW 환경변수를 확인하세요."
        )

    logger.info(f"[login] 로그인 성공: {naver_id}")


# ──────────────────────────────────────────
# 외부 인터페이스 — Context Manager
# ──────────────────────────────────────────
@asynccontextmanager
async def get_logged_in_page() -> AsyncGenerator[Page, None]:
    """
    로그인된 네이버 페이지 반환 (Context Manager)

    사용법:
        async with get_logged_in_page() as page:
            await page.goto("https://cafe.naver.com/alexstock")

    Raises:
        EnvironmentError: NAVER_ID 또는 NAVER_PW 누락
        RuntimeError: 로그인 실패
    """
    naver_id = os.environ.get("NAVER_ID")
    naver_pw = os.environ.get("NAVER_PW")

    if not naver_id or not naver_pw:
        raise EnvironmentError("NAVER_ID 또는 NAVER_PW 환경변수가 누락되었습니다.")

    async with async_playwright() as playwright:
        context = await _create_browser_context(playwright)
        page = await context.new_page()
        try:
            await _do_login(page, naver_id, naver_pw)
            yield page
        finally:
            # 예외 발생 여부 무관하게 브라우저 리소스 정리
            await context.close()
            logger.debug("[login] 브라우저 컨텍스트 종료")
