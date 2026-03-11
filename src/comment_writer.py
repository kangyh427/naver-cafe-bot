# ============================================================
# 파일명: comment_writer.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_writer.py
# 역할:   신규 게시글 환영 댓글 작성 오케스트레이터
#
# 작성일: 2026-03-09
# 수정일: 2026-03-11
# 버전:   v5.0
#
# [v5.0 — 2026-03-11] 모듈 분리 + 근본 버그 수정
#   분리된 모듈:
#     - comment_ai.py  : Gemini AI 댓글 생성 (쿼터 초과 시 즉시 폴백)
#     - comment_dom.py : DOM 접근 전담 (iframe + page 양쪽 지원)
#   이 파일의 역할: 흐름 제어 + 중복 체크 + DB 로깅만 담당
#
#   핵심 버그 수정:
#     [문제] Gemini 429 재시도 대기(210초) × 15개 = 52분 폭발
#            → comment_ai.py에서 즉시 폴백으로 해결
#     [문제] iframe 제거로 textarea를 못 찾던 문제
#            → comment_dom.py에서 iframe + page 양쪽 탐색으로 해결
#
# 안전장치:
#   - 관리자/봇 닉네임 글 자동 스킵
#   - is_post_processed() 중복 체크
#   - 게시글 간 랜덤 딜레이 (3~6초)
# ============================================================

import asyncio
import random
import logging

from playwright.async_api import Page

from comment_ai  import generate_welcome_comment
from comment_dom import read_post_content, submit_comment
from supabase_logger import (
    is_post_processed,
    mark_post_processed,
    log_welcome_comment,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
BOT_NICKNAMES    = ["AlexKang", "알렉스강"]
PAGE_LOAD_WAIT_S = 3.0


# ──────────────────────────────────────────
# 메인 실행 함수
# ──────────────────────────────────────────

async def run_comment_writer(page: Page, post_urls: list[str]) -> int:
    """
    신규 게시글 목록에 환영 댓글 작성
    main.py에서 호출하는 단일 진입점

    흐름:
      1. 중복 체크 (is_post_processed)
      2. 게시글 읽기 (comment_dom.read_post_content)
      3. 관리자/봇 글 스킵
      4. AI 댓글 생성 (comment_ai.generate_welcome_comment)
      5. 댓글 제출 (comment_dom.submit_comment)
      6. DB 로깅 (supabase_logger)

    Returns:
        성공적으로 댓글을 단 게시글 수
    """
    success_count = 0
    logger.info(f"[writer] 시작 | 대상: {len(post_urls)}개")

    for idx, url in enumerate(post_urls):
        try:
            # 1. 중복 체크
            if is_post_processed(url):
                logger.debug(f"[writer] 이미 처리됨 ({idx+1}/{len(post_urls)}): {url[-50:]}")
                continue

            logger.info(f"[writer] 처리 ({idx+1}/{len(post_urls)}): {url[-60:]}")

            # 2. 게시글 이동 및 내용 읽기
            await page.goto(url, timeout=25000, wait_until="domcontentloaded")
            await asyncio.sleep(PAGE_LOAD_WAIT_S)

            title, content, author = await read_post_content(page)

            # 3. 관리자/봇 본인 글 스킵
            if any(bn.lower() in author.lower() for bn in BOT_NICKNAMES):
                logger.debug(f"[writer] 관리자 글 스킵: '{author}'")
                mark_post_processed(url, author)
                continue

            # 4. AI 댓글 생성 (실패 시 즉시 템플릿 폴백)
            comment = generate_welcome_comment(title, content, author)

            # 5. 댓글 제출
            submitted = await submit_comment(page, comment)

            if submitted:
                success_count += 1
                mark_post_processed(url, author)
                log_welcome_comment(url, author, comment)
                logger.info(f"[writer] ✅ 완료: {author} — '{title[:30]}'")
            else:
                logger.warning(f"[writer] ❌ 실패: {url[-60:]}")
                # 실패한 게시글도 processed로 마킹 (무한 재시도 방지)
                mark_post_processed(url, author)

            # 게시글 간 랜덤 딜레이
            await asyncio.sleep(random.uniform(3.0, 6.0))

        except Exception as e:
            logger.error(f"[writer] 오류 [{url[-50:]}]: {e}", exc_info=True)

    logger.info(f"[writer] 완료 | {success_count}/{len(post_urls)}")
    return success_count
