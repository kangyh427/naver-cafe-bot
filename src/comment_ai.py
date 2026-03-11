# ============================================================
# 파일명: comment_ai.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_ai.py
# 역할:   Gemini AI 환영 댓글 생성 전담
#
# 작성일: 2026-03-11
# 버전:   v1.0
#
# 설계 원칙:
#   - Gemini 호출 실패 시 즉시 템플릿 폴백 (재시도 대기 없음)
#   - 쿼터 초과 시 기다리지 않고 템플릿 사용 → 실행 시간 폭발 방지
#   - comment_writer.py / comment_dom.py 와 완전 분리
#
# 안전장치:
#   - Gemini 429/quota → 즉시 템플릿 폴백 (재시도 X)
#   - API 키 없음 → 템플릿 사용
#   - 생성된 댓글 길이 검증 (20~150자)
# ============================================================

import os
import json
import random
import logging
from pathlib import Path

import google.generativeai as genai

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
COMMENT_MIN_LEN = 20
COMMENT_MAX_LEN = 150

DEFAULT_TEMPLATES = [
    "안녕하세요! 알렉스강의 주식이야기 카페에 오신 것을 환영합니다 🎉 좋은 정보 나눠주셔서 감사해요!",
    "환영합니다! 카페에서 좋은 인연 이어가요. 함께 성장하는 투자 커뮤니티가 되길 바랍니다 📈",
    "좋은 글 감사합니다! 카페 활동 활발히 해주세요. 함께 공부하며 성장해요 💪",
    "반갑습니다! 알렉스강 카페에서 함께 투자 공부해요. 언제든 궁금한 점 질문해 주세요 😊",
    "환영해요! 카페에 좋은 글 올려주셔서 감사합니다. 앞으로도 활발한 소통 부탁드립니다 🙌",
]


def _load_templates() -> list[str]:
    """keywords.json에서 환영 템플릿 로드, 실패 시 기본값 사용"""
    try:
        kw_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(kw_path, encoding="utf-8") as f:
            data = json.load(f)
        templates = data.get("welcome_templates", [])
        return templates if templates else DEFAULT_TEMPLATES
    except Exception:
        return DEFAULT_TEMPLATES


# 모듈 로드 시 1회만 로드
WELCOME_TEMPLATES: list[str] = _load_templates()


def _get_gemini_model():
    """Gemini 클라이언트 생성, 실패 시 None 반환"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[ai] GEMINI_API_KEY 없음 → 템플릿 사용")
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.0-flash")
    except Exception as e:
        logger.error(f"[ai] Gemini 초기화 실패: {e}")
        return None


def generate_welcome_comment(
    post_title: str,
    post_content: str,
    author: str,
) -> str:
    """
    Gemini AI로 환영 댓글 생성
    실패(429 포함) 시 즉시 템플릿 폴백 — 재시도 대기 없음

    핵심 변경 (v1.0):
      - 이전: 429 발생 시 30초→60초→120초 대기 후 재시도
      - 현재: 429 발생 시 즉시 random.choice(WELCOME_TEMPLATES) 반환
      → 게시글 15개 × 210초 대기 = 52분 폭발 방지

    Returns:
        생성된 댓글 문자열 (20~150자 보장)
    """
    model = _get_gemini_model()
    if not model:
        return random.choice(WELCOME_TEMPLATES)

    prompt = f"""당신은 한국 주식 투자 카페 '알렉스강의 주식이야기'의 관리자입니다.
신규 게시글에 따뜻하고 자연스러운 환영 댓글을 작성해 주세요.
게시글 제목: {post_title}
게시글 내용: {post_content[:200]}
작성자: {author}
요구사항: 20~150자, 게시글과 자연스럽게 연결, 이모지 1~2개, 댓글 내용만 작성"""

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
        if len(comment) > COMMENT_MAX_LEN:
            return comment[:COMMENT_MAX_LEN]
        # 너무 짧으면 템플릿
        return random.choice(WELCOME_TEMPLATES)

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "quota" in err_str.lower():
            logger.warning("[ai] Gemini 쿼터 초과 → 즉시 템플릿 폴백 (대기 없음)")
        else:
            logger.error(f"[ai] Gemini 생성 실패: {e}")
        return random.choice(WELCOME_TEMPLATES)
