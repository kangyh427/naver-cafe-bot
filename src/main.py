# ============================================================
# 파일명: main.py
# 경로:   kangyh427/naver_cafe_bot/src/main.py
# 역할:   봇 전체 실행 흐름 제어 (오케스트레이터)
#         GitHub Actions 진입점
#
# 작성일: 2026-03-09
# 버전:   v1.0
#
# 실행 순서:
#   1. 환경변수 검증
#   2. 네이버 로그인 (naver_login.py)
#   3. 카페 모니터링 — 스팸 감지/삭제 (cafe_monitor.py)
#   4. 환영 댓글 작성 (comment_writer.py)
#   5. 실행 결과 DB 저장 (supabase_logger.py)
#
# 안전장치:
#   - 단계별 독립 예외 처리 (한 단계 실패가 전체 중단 방지)
#   - 실행 시간 측정 및 로그 저장
#   - 종료 코드: 0 (성공/부분성공), 1 (로그인 실패 등 치명적 오류)
#   - 로깅: 콘솔 + GitHub Actions에서 바로 확인 가능한 포맷
# ============================================================

import asyncio
import logging
import sys
import time
from typing import Optional

from naver_login import get_logged_in_page
from cafe_monitor import run_monitor
from comment_writer import run_comment_writer
from supabase_logger import log_bot_run

# ──────────────────────────────────────────
# 기능 플래그 (임시 비활성화 시 False로 설정)
# ──────────────────────────────────────────
ENABLE_COMMENT_WRITING = False   # ← 댓글 작성 비활성화 (DOM 수정 중)
ENABLE_SPAM_DELETION   = True    # ← 스팸 감지+삭제 활성화

# ──────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# 환경변수 검증
# ──────────────────────────────────────────
REQUIRED_ENV_VARS = [
    "NAVER_ID",
    "NAVER_PW",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "GEMINI_API_KEY",
]

def validate_env() -> bool:
    """
    필수 환경변수 존재 여부 확인
    Returns: True (모두 존재) / False (누락 있음)
    """
    import os
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        logger.error(f"[main] 환경변수 누락: {', '.join(missing)}")
        logger.error("[main] GitHub Secrets에 해당 변수가 등록되어 있는지 확인하세요.")
        return False
    logger.info("[main] 환경변수 검증 완료")
    return True


# ──────────────────────────────────────────
# 메인 실행 로직
# ──────────────────────────────────────────
async def run_bot() -> int:
    """
    봇 전체 실행
    Returns: 종료 코드 (0: 성공, 1: 치명적 오류)
    """
    start_time = time.time()
    logger.info("=" * 50)
    logger.info("[main] 네이버 카페봇 시작")
    logger.info("=" * 50)

    # 1. 환경변수 검증
    if not validate_env():
        return 1

    # 실행 통계
    posts_checked    = 0
    spam_deleted     = 0
    welcome_commented = 0
    error_count      = 0
    status           = "success"
    error_message: Optional[str] = None

    try:
        # 2. 네이버 로그인 + 전체 봇 실행
        async with get_logged_in_page() as page:
            logger.info("[main] 네이버 로그인 완료 — 모니터링 시작")

            # 3. 카페 모니터링 (스팸 감지 / 조건부 삭제)
            try:
                monitor_result = await run_monitor(
                    page,
                    enable_deletion=ENABLE_SPAM_DELETION,
                )
                posts_checked  = monitor_result.posts_checked
                spam_deleted   = monitor_result.spam_deleted
                error_count   += monitor_result.errors
                new_post_urls  = monitor_result.new_post_urls

                logger.info(
                    f"[main] 모니터링 완료 | "
                    f"게시글:{posts_checked} "
                    f"스팸감지:{monitor_result.spam_detected} "
                    f"스팸삭제:{spam_deleted} "
                    f"오류:{monitor_result.errors}"
                )
            except Exception as e:
                logger.error(f"[main] 모니터링 단계 오류: {e}")
                error_count += 1
                new_post_urls = []
                status = "partial_error"

            # 4. 환영 댓글 작성 (현재 비활성화)
            if not ENABLE_COMMENT_WRITING:
                logger.info(
                    "[main] 환영 댓글 작성 비활성화 상태 (ENABLE_COMMENT_WRITING=False)"
                )
            elif new_post_urls:
                try:
                    welcome_commented = await run_comment_writer(page, new_post_urls)
                    logger.info(f"[main] 환영 댓글 완료 | 작성:{welcome_commented}개")
                except Exception as e:
                    logger.error(f"[main] 환영 댓글 단계 오류: {e}")
                    error_count += 1
                    status = "partial_error"
            else:
                logger.info("[main] 신규 게시글 없음 — 환영 댓글 스킵")

    except EnvironmentError as e:
        # 환경변수 오류 — 치명적
        logger.error(f"[main] 환경변수 오류: {e}")
        return 1

    except RuntimeError as e:
        # 로그인 실패 — 치명적
        logger.error(f"[main] 로그인 실패: {e}")
        error_message = str(e)
        status = "failed"
        error_count += 1

    except Exception as e:
        # 예상치 못한 오류
        logger.error(f"[main] 예기치 않은 오류: {e}", exc_info=True)
        error_message = str(e)
        status = "failed"
        error_count += 1

    finally:
        # 5. 실행 결과 DB 저장 (항상 실행)
        duration = time.time() - start_time
        log_bot_run(
            posts_checked=posts_checked,
            spam_deleted=spam_deleted,
            welcome_commented=welcome_commented,
            error_count=error_count,
            run_duration_sec=duration,
            status=status,
            error_message=error_message,
        )

        logger.info("=" * 50)
        logger.info(
            f"[main] 봇 종료 | 상태:{status} | "
            f"소요:{duration:.1f}초 | "
            f"게시글:{posts_checked} 스팸:{spam_deleted} 환영:{welcome_commented}"
        )
        logger.info("=" * 50)

    return 0 if status != "failed" else 1


# ──────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────
if __name__ == "__main__":
    exit_code = asyncio.run(run_bot())
    sys.exit(exit_code)
