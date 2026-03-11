# ============================================================
# 파일명: supabase_logger.py
# 경로:   kangyh427/naver_cafe_bot/src/supabase_logger.py
# 역할:   Supabase DB 로그 저장 — 4개 테이블 CRUD 전담
#
# 작성일: 2026-03-09
# 수정일: 2026-03-10
# 버전:   v1.1
#
# [v1.1 — 2026-03-10]
#   Bug Fix: DB 실제 컬럼명과 불일치로 bot_run_logs 저장 실패
#     - welcome_commented → welcome_sent
#     - error_count 제거 (DB에 없음)
#     - run_duration_sec 제거 (DB에 없음)
#     - comments_checked 추가
#
# [v1.0 — 2026-03-09]
#   최초 작성
#
# 안전장치:
#   - 모든 DB 작업 try/except 래핑 — 로거 실패가 메인 로직 중단 금지
#   - insert 실패 시 False 반환, 예외 미전파
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
    """Supabase 클라이언트 싱글톤 반환"""
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
    """삭제된 스팸 댓글 기록 저장"""
    try:
        supabase = get_supabase()
        supabase.table("spam_logs").insert({
            "post_url":        post_url,
            "comment_author":  comment_author,
            "comment_content": comment_content[:1000],
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
    """작성된 환영 댓글 기록 저장"""
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
    """이미 환영 댓글을 단 게시글인지 확인"""
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
        return False


def mark_post_processed(post_url: str, post_author: str = "") -> bool:
    """
    처리 완료 게시글 URL 등록

    DB 실제 컬럼: id, post_url, post_type, processed_at
    (post_author 컬럼 없음 → post_type에 'welcome'으로 저장)
    """
    try:
        supabase = get_supabase()
        supabase.table("processed_posts").insert({
            "post_url":     post_url,
            "post_type":    "welcome",
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

    v1.1: DB 실제 컬럼명에 맞춤
      - welcome_commented → welcome_sent
      - error_count, run_duration_sec → DB에 없으므로 저장 안 함
      - comments_checked → posts_checked 값 재사용

    함수 시그니처는 main.py 호환을 위해 유지하되,
    DB insert 시 실제 컬럼명으로 매핑
    """
    try:
        supabase = get_supabase()
        supabase.table("bot_run_logs").insert({
            "posts_checked":     posts_checked,
            "comments_checked":  0,
            "spam_deleted":      spam_deleted,
            "welcome_sent":      welcome_commented,
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
