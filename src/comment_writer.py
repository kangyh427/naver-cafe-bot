# ============================================================
# 파일명: comment_writer.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_writer.py
# 역할:   신규 게시글에 Gemini AI 환영 댓글 자동 작성
#
# 작성일: 2026-03-09
# 버전:   v1.0
#
# 의존성:
#   - google-generativeai (pip install google-generativeai)
#   - 환경변수: GEMINI_API_KEY
#   - config/keywords.json (환영 댓글 템플릿 — AI 실패 시 fallback)
#   - supabase_logger.py (중복 방지 + 로그 저장)
#
# 작동 흐름:
#   1. processed_posts 확인 → 이미 처리된 글 스킵
#   2. 게시글 내용 읽기
#   3. Gemini AI로 맞춤 환영 댓글 생성
#      └─ AI 실패 시 템플릿 fallback
#   4. 댓글 입력창에 작성
#   5. processed_posts 등록 + welcome_logs 저장
#
# 안전장치:
#   - is_post_processed() 로 중복 댓글 방지
#   - 관리자 본인 게시글 건너뜀
#   - AI 오류 시 5개 템플릿 중 랜덤 선택 fallback
#   - 댓글 입력/제출 실패 시 로그만 남기고 계속 진행
# ============================================================

import asyncio
import random
import json
import logging
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from playwright.async_api import Page

from supabase_logger import (
    is_post_processed,
    mark_post_processed,
    log_welcome_comment,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
BOT_NICKNAME     = "AlexKang"           # 관리자 닉네임 (본인 글 제외용)
PAGE_LOAD_WAIT_S = 2.0
COMMENT_MIN_LEN  = 20                   # 환영 댓글 최소 길이
COMMENT_MAX_LEN  = 150                  # 환영 댓글 최대 길이


# ──────────────────────────────────────────
# 환영 댓글 템플릿 (AI 실패 시 fallback)
# ──────────────────────────────────────────
DEFAULT_TEMPLATES = [
    "안녕하세요! 알렉스강의 주식이야기 카페에 오신 것을 환영합니다 🎉 좋은 정보 나눠주셔서 감사해요!",
    "환영합니다! 카페에서 좋은 인연 이어가요. 함께 성장하는 투자 커뮤니티가 되길 바랍니다 📈",
    "좋은 글 감사합니다! 카페 활동 활발히 해주세요. 함께 공부하며 성장해요 💪",
    "반갑습니다! 알렉스강 카페에서 함께 투자 공부해요. 언제든 궁금한 점 질문해 주세요 😊",
    "환영해요! 카페에 좋은 글 올려주셔서 감사합니다. 앞으로도 활발한 소통 부탁드립니다 🙌",
]

def _load_templates() -> list[str]:
    """
    config/keywords.json에서 환영 댓글 템플릿 로드
    실패 시 기본 템플릿 사용 (봇 중단 방지)
    """
    try:
        keywords_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(keywords_path, encoding="utf-8") as f:
            data = json.load(f)
        templates = data.get("welcome_templates", [])
        if templates:
            return templates
    except Exception as e:
        logger.debug(f"[writer] 템플릿 로드 실패 → 기본 사용: {e}")
    return DEFAULT_TEMPLATES

WELCOME_TEMPLATES: list[str] = _load_templates()


# ──────────────────────────────────────────
# Gemini AI 환영 댓글 생성
# ──────────────────────────────────────────
def _get_gemini_model():
    """Gemini 1.5 Flash 모델 반환 (실패 시 None)"""
    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.0-flash")
    except Exception:
        return None


def generate_welcome_comment(post_title: str, post_content: str, author: str) -> str:
    """
    Gemini AI로 게시글 맞춤 환영 댓글 생성
    AI 실패 시 템플릿 fallback (항상 댓글 반환 보장)

    Args:
        post_title:   게시글 제목
        post_content: 게시글 내용 (앞 300자)
        author:       게시글 작성자
    Returns:
        환영 댓글 문자열 (20~150자)
    """
    model = _get_gemini_model()
    if not model:
        logger.warning("[writer] Gemini 모델 없음 → 템플릿 fallback")
        return random.choice(WELCOME_TEMPLATES)

    prompt = f"""
당신은 한국 주식 투자 카페 '알렉스강의 주식이야기'의 관리자입니다.
신규 게시글에 따뜻하고 자연스러운 환영 댓글을 작성해 주세요.

게시글 제목: {post_title}
게시글 내용 (앞부분): {post_content[:300]}
작성자: {author}

요구사항:
- 20자 이상 150자 이하
- 게시글 내용과 자연스럽게 연결
- 주식/투자 카페 분위기에 맞게 (너무 딱딱하지 않게)
- 이모지 1~2개 사용 가능
- 댓글 내용만 작성 (다른 설명 없이)
"""

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.8,
                max_output_tokens=200,
            ),
        )
        comment = response.text.strip()

        # 길이 검증
        if COMMENT_MIN_LEN <= len(comment) <= COMMENT_MAX_LEN:
            return comment
        elif len(comment) > COMMENT_MAX_LEN:
            return comment[:COMMENT_MAX_LEN]
        else:
            logger.debug(f"[writer] AI 응답 너무 짧음({len(comment)}자) → 템플릿 fallback")
            return random.choice(WELCOME_TEMPLATES)

    except Exception as e:
        logger.error(f"[writer] Gemini 호출 실패: {e}")
        return random.choice(WELCOME_TEMPLATES)


# ──────────────────────────────────────────
# 게시글 내용 읽기
# ──────────────────────────────────────────
async def _read_post_content(page: Page) -> tuple[str, str, str]:
    """
    현재 페이지에서 게시글 제목/내용/작성자 추출
    Returns: (title, content, author)
    """
    try:
        # iframe 전환
        try:
            frame = page.frame_locator("iframe#cafe_main").first
        except Exception:
            frame = page

        title_el   = frame.locator(".title-text, .tit-box .title").first
        content_el = frame.locator(".se-main-container, .tbody").first
        author_el  = frame.locator(".writer-nick-wrap, .cafe-nick-name").first

        title   = (await title_el.text_content(timeout=5000)  or "").strip()
        content = (await content_el.text_content(timeout=5000) or "").strip()
        author  = (await author_el.text_content(timeout=5000)  or "알수없음").strip()

        return title, content, author

    except Exception as e:
        logger.debug(f"[writer] 게시글 내용 읽기 실패: {e}")
        return "", "", "알수없음"


# ──────────────────────────────────────────
# 환영 댓글 입력 및 제출
# ──────────────────────────────────────────
async def _submit_comment(page: Page, comment_text: str) -> bool:
    """
    댓글 입력창에 환영 댓글 작성 및 제출
    Returns: True (성공) / False (실패)
    """
    try:
        try:
            frame = page.frame_locator("iframe#cafe_main").first
        except Exception:
            frame = page

        # 댓글 입력창 클릭
        comment_input = frame.locator(
            ".comment-textarea, textarea[name='content'], .CommentBox textarea"
        ).first
        await comment_input.click(timeout=5000)
        await asyncio.sleep(0.5)

        # 텍스트 입력 (자연스러운 속도)
        await comment_input.type(comment_text, delay=random.randint(50, 120))
        await asyncio.sleep(random.uniform(0.8, 1.5))

        # 등록 버튼 클릭
        submit_btn = frame.locator(
            ".btn-comment-write, button[type='submit'].comment, .CommentBox .btn_register"
        ).first
        await submit_btn.click(timeout=5000)
        await asyncio.sleep(2.0)

        return True

    except Exception as e:
        logger.error(f"[writer] 댓글 제출 실패: {e}")
        return False


# ──────────────────────────────────────────
# 메인 실행 함수
# ──────────────────────────────────────────
async def run_comment_writer(page: Page, post_urls: list[str]) -> int:
    """
    신규 게시글 목록에 환영 댓글 작성
    외부(main.py)에서 호출하는 단일 진입점

    Args:
        page:      로그인된 네이버 페이지
        post_urls: cafe_monitor.py에서 받은 게시글 URL 목록
    Returns:
        작성 성공한 댓글 수
    """
    success_count = 0

    for url in post_urls:
        try:
            # 1. 중복 확인
            if is_post_processed(url):
                logger.debug(f"[writer] 이미 처리됨, 스킵: {url[:60]}")
                continue

            # 2. 게시글 진입
            await page.goto(url, timeout=15000)
            await asyncio.sleep(PAGE_LOAD_WAIT_S)

            # 3. 내용 읽기
            title, content, author = await _read_post_content(page)

            # 4. 관리자 본인 글 스킵
            if author == BOT_NICKNAME:
                logger.debug(f"[writer] 본인 글 스킵: {title[:30]}")
                continue

            # 5. AI 환영 댓글 생성
            comment = generate_welcome_comment(title, content, author)

            # 6. 댓글 작성
            submitted = await _submit_comment(page, comment)

            if submitted:
                success_count += 1
                # 7. DB 등록
                mark_post_processed(url, author)
                log_welcome_comment(url, author, comment)
                logger.info(f"[writer] 환영 댓글 작성 완료: {author} — '{title[:30]}'")
            else:
                logger.warning(f"[writer] 댓글 제출 실패: {url[:60]}")

            # 게시글 간 딜레이 (계정 보호)
            await asyncio.sleep(random.uniform(3.0, 6.0))

        except Exception as e:
            logger.error(f"[writer] 게시글 처리 오류 [{url[:50]}]: {e}")

    logger.info(f"[writer] 완료 | 작성:{success_count}/{len(post_urls)}")
    return success_count
