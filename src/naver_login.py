# ============================================================
# 파일명: naver_login.py
# 경로:   kangyh427/naver_cafe_bot/src/naver_login.py
# 역할:   Playwright 브라우저 초기화 + 네이버 로그인/세션 관리
#
# 작성일: 2026-03-09
# 수정일: 2026-03-10
# 버전:   v2.0
#
# [v2.0 — 2026-03-10]
#   개선: 쿠키 저장/재사용 방식 도입 (봇 탐지 위험 대폭 감소)
#     - 매 실행마다 ID/PW 로그인 → 쿠키 있으면 세션 복원으로 변경
#     - session_manager.py 와 연동 (역할 분리)
#     - 쿠키 무효 시 자동 재로그인 후 새 쿠키 저장
#
# [v1.0 — 2026-03-09]
#   최초 작성
#
# 실행 흐름 (v2.0):
#   1. Supabase에서 저장된 쿠키 조회
#   2-A. 쿠키 있음 → 브라우저에 쿠키 적용 → 세션 유효성 검증
#        유효 → 로그인 생략 (봇 탐지 위험 최소화)
#        무효 → 3번으로
#   2-B. 쿠키 없음 → 3번으로
#   3. ID/PW 로그인 실행
#   4. 로그인 성공 → 새 쿠키 Supabase 저장
#
# 안전장치:
#   - 쿠키 복원 실패 시 ID/PW 로그인으로 자동 fallback
#   - 환경변수 누락 시 즉시 예외 (undefined behavior 방지)
#   - 로그인 실패(캡차, 2차인증 등) 명확한 예외 메시지
#   - 브라우저 비정상 종료 시에도 리소스 정리 보장
# ============================================================

import os
import asyncio
import random
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import async_playwright, Page, BrowserContext

from session_manager import load_cookies, save_cookies, verify_session

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 타이밍 상수 (계정 보호용)
# ──────────────────────────────────────────
TYPE_DELAY_MIN_MS  = 80
TYPE_DELAY_MAX_MS  = 200
ACTION_DELAY_MIN_S = 1.0
ACTION_DELAY_MAX_S = 3.0
LOGIN_TIMEOUT_MS   = 15000

NAVER_LOGIN_URL = "https://nid.naver.com/nidlogin.login"
NAVER_MAIN_URL  = "https://www.naver.com"


def _human_delay() -> float:
    return random.uniform(ACTION_DELAY_MIN_S, ACTION_DELAY_MAX_S)


async def _type_humanlike(page: Page, selector: str, text: str) -> None:
    """사람처럼 한 글자씩 타이핑 (봇 탐지 우회)"""
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.3, 0.7))
    await page.type(selector, text, delay=random.randint(TYPE_DELAY_MIN_MS, TYPE_DELAY_MAX_MS))


# ──────────────────────────────────────────
# 브라우저 컨텍스트 초기화
# ──────────────────────────────────────────
async def _create_browser_context(playwright) -> BrowserContext:
    """헤드리스 Chromium 브라우저 컨텍스트 생성"""
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
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
# ID/PW 직접 로그인 (쿠키 없거나 만료 시)
# ──────────────────────────────────────────
async def _do_login(page: Page, naver_id: str, naver_pw: str) -> None:
    """
    네이버 ID/PW 로그인 실행
    성공 시 session_manager를 통해 쿠키 자동 저장
    Raises:
        RuntimeError: 로그인 실패 (캡차, 2차 인증 등)
    """
    logger.info("[login] ID/PW 로그인 시작...")
    await page.goto(NAVER_LOGIN_URL, timeout=LOGIN_TIMEOUT_MS)
    await asyncio.sleep(_human_delay())

    await _type_humanlike(page, "#id", naver_id)
    await asyncio.sleep(random.uniform(0.5, 1.0))
    await _type_humanlike(page, "#pw", naver_pw)
    await asyncio.sleep(random.uniform(0.5, 1.2))

    await page.click(".btn_login")
    await asyncio.sleep(2.0)

    current_url = page.url

    if "captcha" in current_url or "challenge" in current_url:
        raise RuntimeError(
            "[login] 캡차 페이지 감지 — 수동 로그인 필요. "
            "네이버 계정 보안 설정 확인 요망."
        )

    if "nidlogin" in current_url and "otp" in current_url.lower():
        raise RuntimeError("[login] 2단계 인증 필요 — 수동 처리 요망.")

    # 로그인 유지 팝업 처리
    try:
        btn = page.locator("text=다음에 하기")
        if await btn.is_visible(timeout=2000):
            await btn.click()
            await asyncio.sleep(1.0)
    except Exception:
        pass

    # 로그인 성공 검증
    await page.goto(NAVER_MAIN_URL, timeout=LOGIN_TIMEOUT_MS)
    await asyncio.sleep(1.5)

    is_logged_in = await page.locator(
        ".gnb_my_area, .MyView-module__link_login___HpHMW"
    ).count() > 0

    if not is_logged_in:
        raise RuntimeError(
            f"[login] 로그인 실패 — 현재 URL: {page.url}. "
            "NAVER_ID, NAVER_PW 환경변수를 확인하세요."
        )

    logger.info(f"[login] ID/PW 로그인 성공: {naver_id}")

    # ── 쿠키 저장 (다음 실행부터 재사용) ──
    cookies = await page.context.cookies()
    save_cookies(cookies)


# ──────────────────────────────────────────
# 쿠키로 세션 복원 시도
# ──────────────────────────────────────────
async def _restore_session(context: BrowserContext, page: Page) -> bool:
    """
    저장된 쿠키로 세션 복원 시도
    Returns:
        True (복원 성공, 로그인 생략 가능)
        False (쿠키 없음 또는 만료 → ID/PW 로그인 필요)
    """
    cookies = load_cookies()
    if not cookies:
        return False

    try:
        # 브라우저 컨텍스트에 쿠키 적용
        await context.add_cookies(cookies)
        logger.info(f"[login] 저장된 쿠키 {len(cookies)}개 적용 — 세션 복원 시도")

        # 실제 접속으로 유효성 검증
        is_valid = await verify_session(page)
        return is_valid

    except Exception as e:
        logger.error(f"[login] 쿠키 복원 실패: {e}")
        return False


# ──────────────────────────────────────────
# 외부 인터페이스 — Context Manager
# ──────────────────────────────────────────
@asynccontextmanager
async def get_logged_in_page() -> AsyncGenerator[Page, None]:
    """
    로그인된 네이버 페이지 반환 (Context Manager)

    v2.0 흐름:
        1. 저장된 쿠키 있으면 → 세션 복원 (로그인 생략)
        2. 쿠키 없거나 만료 → ID/PW 로그인 후 쿠키 저장

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
            # 1차 시도: 쿠키 세션 복원
            session_restored = await _restore_session(context, page)

            if not session_restored:
                # 2차 시도: ID/PW 로그인 (쿠키 자동 저장 포함)
                logger.info("[login] 쿠키 세션 없음 → ID/PW 로그인 실행")
                await _do_login(page, naver_id, naver_pw)

            yield page

        finally:
            await context.close()
            logger.debug("[login] 브라우저 컨텍스트 종료")
