# ============================================================
# 파일명: supabase_logger.py
# 경로:   kangyh427/naver_cafe_bot/src/supabase_logger.py
# 역할:   Supabase DB 로그 저장 — 4개 테이블 CRUD 전담
#
# 작성일: 2026-03-09
# 버전:   v1.0
#
# 의존성:
#   - supabase-py (pip install supabase)
#   - 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
#
# 테이블 구조:
#   spam_logs       — 삭제된 스팸 댓글 기록
#   welcome_logs    — 작성된 환영 댓글 기록
#   processed_posts — 처리 완료 게시글 URL (중복 방지)
#   bot_run_logs    — 봇 실행 이력 및 통계
#
# 안전장치:
#   - 모든 DB 작업 try/except 래핑 — 로거 실패가 메인 로직 중단 금지
#   - insert 실패 시 False 반환, 예외 미전파
#   - 환경변수 누락 시 명확한 에러 메시지 출력
# ============================================================

import os
import logging
from datetime import datetime, timezone
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# Supabase 클라이언트 싱글톤
# ──────────────────────────────────────────
_client: Optional[Client] = None

def get_supabase() -> Client:
    """Supabase 클라이언트 싱글톤 반환 — 환경변수 누락 시 즉시 예외"""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise EnvironmentError(
                "SUPABASE_URL 또는 SUPABASE_SERVICE_KEY 환경변수가 누락되었습니다."
            )
        _client = create_client(url, key)
    return _client


def _now_iso() -> str:
    """현재 시각 ISO 8601 형식 (UTC)"""
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────
# 스팸 로그 저장
# ──────────────────────────────────────────
def log_spam_deleted(
    post_url: str,
    comment_author: str,
    comment_content: str,
    spam_reason: str,
    ai_confidence: Optional[float] = None,
    keyword_matched: Optional[str] = None,
) -> bool:
    """
    삭제된 스팸 댓글 기록 저장
    Returns: True (저장 성공) / False (실패)
    """
    try:
        supabase = get_supabase()
        supabase.table("spam_logs").insert({
            "post_url":        post_url,
            "comment_author":  comment_author,
            "comment_content": comment_content[:1000],  # DB 컬럼 길이 안전장치
            "spam_reason":     spam_reason,
            "ai_confidence":   ai_confidence,
            "keyword_matched": keyword_matched,
            "deleted_at":      _now_iso(),
        }).execute()
        logger.info(f"[logger] 스팸 로그 저장 완료: {comment_author}")
        return True
    except Exception as e:
        logger.error(f"[logger] 스팸 로그 저장 실패: {e}")
        return False


# ──────────────────────────────────────────
# 환영 댓글 로그 저장
# ──────────────────────────────────────────
def log_welcome_comment(
    post_url: str,
    post_author: str,
    comment_content: str,
) -> bool:
    """
    작성된 환영 댓글 기록 저장
    Returns: True (저장 성공) / False (실패)
    """
    try:
        supabase = get_supabase()
        supabase.table("welcome_logs").insert({
            "post_url":        post_url,
            "post_author":     post_author,
            "comment_content": comment_content[:1000],
            "commented_at":    _now_iso(),
        }).execute()
        logger.info(f"[logger] 환영 댓글 로그 저장 완료: {post_author}")
        return True
    except Exception as e:
        logger.error(f"[logger] 환영 댓글 로그 저장 실패: {e}")
        return False


# ──────────────────────────────────────────
# 처리된 게시글 URL 관리 (중복 방지)
# ──────────────────────────────────────────
def is_post_processed(post_url: str) -> bool:
    """
    이미 환영 댓글을 단 게시글인지 확인
    Returns: True (이미 처리됨) / False (미처리 또는 조회 실패)
    안전장치: DB 조회 실패 시 False 반환 → 중복보다 누락 방지 우선
    """
    try:
        supabase = get_supabase()
        result = (
            supabase.table("processed_posts")
            .select("id")
            .eq("post_url", post_url)
            .limit(1)
            .execute()
        )
        return len(result.data) > 0
    except Exception as e:
        logger.error(f"[logger] processed_posts 조회 실패: {e}")
        return False  # 실패 시 안전하게 미처리로 간주


def mark_post_processed(post_url: str, post_author: str) -> bool:
    """
    처리 완료 게시글 URL 등록
    Returns: True (등록 성공) / False (실패)
    """
    try:
        supabase = get_supabase()
        supabase.table("processed_posts").insert({
            "post_url":    post_url,
            "post_author": post_author,
            "processed_at": _now_iso(),
        }).execute()
        return True
    except Exception as e:
        logger.error(f"[logger] processed_posts 등록 실패: {e}")
        return False


# ──────────────────────────────────────────
# 봇 실행 이력 저장
# ──────────────────────────────────────────
def log_bot_run(
    posts_checked: int,
    spam_deleted: int,
    welcome_commented: int,
    error_count: int,
    run_duration_sec: float,
    status: str = "success",
    error_message: Optional[str] = None,
) -> bool:
    """
    봇 1회 실행 결과 통계 저장
    status: "success" | "partial_error" | "failed"
    Returns: True (저장 성공) / False (실패)
    """
    try:
        supabase = get_supabase()
        supabase.table("bot_run_logs").insert({
            "posts_checked":     posts_checked,
            "spam_deleted":      spam_deleted,
            "welcome_commented": welcome_commented,
            "error_count":       error_count,
            "run_duration_sec":  round(run_duration_sec, 2),
            "status":            status,
            "error_message":     error_message,
            "run_at":            _now_iso(),
        }).execute()
        logger.info(
            f"[logger] 실행 로그 저장 완료 | "
            f"게시글:{posts_checked} 스팸:{spam_deleted} 환영:{welcome_commented} "
            f"오류:{error_count} ({run_duration_sec:.1f}초)"
        )
        return True
    except Exception as e:
        logger.error(f"[logger] 봇 실행 로그 저장 실패: {e}")
        return False
