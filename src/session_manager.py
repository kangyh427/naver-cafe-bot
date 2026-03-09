# ============================================================
# 파일명: session_manager.py
# 경로:   kangyh427/naver_cafe_bot/src/session_manager.py
# 역할:   네이버 세션 쿠키 저장/로드/검증 전담
#
# 작성일: 2026-03-10
# 버전:   v1.0
#
# 설계 원칙:
#   - naver_login.py 에서 로그인 성공 후 이 모듈로 쿠키 저장
#   - 다음 실행 시 쿠키 복원 → 로그인 생략
#   - 쿠키 만료/무효 시 자동 감지 → 재로그인 트리거
#   - Supabase naver_sessions 테이블에 암호화 없이 저장
#     (GitHub Actions 환경 특성상 Supabase가 가장 안전)
#
# 쿠키 유효성 판단 기준:
#   1. DB에 is_valid=True 레코드 존재
#   2. expires_at이 현재 시각 이후
#   3. 실제 페이지 접근 후 로그인 상태 확인 (최종 검증)
#
# 안전장치:
#   - DB 조회 실패 시 → 재로그인으로 fallback (봇 중단 방지)
#   - 쿠키 로드 실패 시 → 재로그인으로 fallback
#   - 만료 쿠키 자동 무효화 처리
# ============================================================

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 쿠키 유효 기간 (네이버 세션 일반적으로 30일, 보수적으로 7일 설정)
COOKIE_VALID_DAYS = 7


# ──────────────────────────────────────────
# Supabase 클라이언트 import (순환 참조 방지용 지연 import)
# ──────────────────────────────────────────
def _get_supabase():
    """supabase_logger의 싱글톤 클라이언트 재사용"""
    from supabase_logger import get_supabase
    return get_supabase()


# ──────────────────────────────────────────
# 쿠키 저장
# ──────────────────────────────────────────
def save_cookies(cookies: list[dict]) -> bool:
    """
    로그인 성공 후 쿠키를 Supabase에 저장
    기존 유효 세션은 모두 무효화 후 새 세션 저장 (1개만 유지)

    Args:
        cookies: Playwright context.cookies() 결과
    Returns:
        True (저장 성공) / False (실패)
    """
    try:
        supabase = _get_supabase()

        # 기존 세션 전체 무효화
        supabase.table("naver_sessions").update(
            {"is_valid": False}
        ).eq("is_valid", True).execute()

        # 새 쿠키 저장
        expires_at = datetime.now(timezone.utc) + timedelta(days=COOKIE_VALID_DAYS)
        supabase.table("naver_sessions").insert({
            "cookies":    json.dumps(cookies, ensure_ascii=False),
            "expires_at": expires_at.isoformat(),
            "is_valid":   True,
        }).execute()

        logger.info(f"[session] 쿠키 저장 완료 (유효기간: {COOKIE_VALID_DAYS}일)")
        return True

    except Exception as e:
        logger.error(f"[session] 쿠키 저장 실패: {e}")
        return False


# ──────────────────────────────────────────
# 쿠키 로드
# ──────────────────────────────────────────
def load_cookies() -> Optional[list[dict]]:
    """
    Supabase에서 유효한 쿠키 로드
    Returns:
        쿠키 목록 / None (유효한 세션 없음 또는 조회 실패)
    """
    try:
        supabase = _get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()

        result = (
            supabase.table("naver_sessions")
            .select("cookies, expires_at")
            .eq("is_valid", True)
            .gt("expires_at", now_iso)   # 만료되지 않은 것만
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            logger.info("[session] 유효한 저장 세션 없음 → 재로그인 필요")
            return None

        cookies = json.loads(result.data[0]["cookies"])
        expires_at = result.data[0]["expires_at"]
        logger.info(f"[session] 저장된 쿠키 로드 성공 (만료: {expires_at[:10]})")
        return cookies

    except Exception as e:
        logger.error(f"[session] 쿠키 로드 실패: {e}")
        return None


# ──────────────────────────────────────────
# 쿠키 무효화
# ──────────────────────────────────────────
def invalidate_cookies() -> bool:
    """
    저장된 세션 전체 무효화 (로그인 실패 또는 세션 만료 감지 시 호출)
    Returns:
        True (성공) / False (실패)
    """
    try:
        supabase = _get_supabase()
        supabase.table("naver_sessions").update(
            {"is_valid": False}
        ).eq("is_valid", True).execute()
        logger.info("[session] 저장된 세션 무효화 완료")
        return True
    except Exception as e:
        logger.error(f"[session] 세션 무효화 실패: {e}")
        return False


# ──────────────────────────────────────────
# 로그인 상태 확인 (페이지 접근 후 실제 검증)
# ──────────────────────────────────────────
async def verify_session(page) -> bool:
    """
    쿠키 복원 후 실제 네이버 페이지에서 로그인 상태 검증
    Args:
        page: Playwright Page 객체 (쿠키 적용 완료 상태)
    Returns:
        True (로그인 유효) / False (세션 만료)
    """
    try:
        await page.goto("https://www.naver.com", timeout=15000)

        # 로그인 상태 확인: 내 정보 영역 존재 여부
        is_logged_in = await page.locator(
            ".gnb_my_area, .MyView-module__link_login___HpHMW"
        ).count() > 0

        if is_logged_in:
            logger.info("[session] 쿠키 세션 유효 확인 완료")
        else:
            logger.warning("[session] 쿠키 세션 만료 감지 → 재로그인 필요")
            invalidate_cookies()  # DB에서도 무효화

        return is_logged_in

    except Exception as e:
        logger.error(f"[session] 세션 검증 실패: {e}")
        return False
