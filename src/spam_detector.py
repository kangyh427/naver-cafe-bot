# ============================================================
# 파일명: spam_detector.py
# 경로:   kangyh427/naver_cafe_bot/src/spam_detector.py
# 역할:   스팸 댓글 2단계 판별 엔진
#         1차: 키워드 필터 (빠른 차단)
#         2차: Gemini 1.5 Flash AI 판별 (정밀 분석)
#
# 작성일: 2026-03-09
# 버전:   v1.0
#
# 의존성:
#   - google-generativeai (pip install google-generativeai)
#   - 환경변수: GEMINI_API_KEY
#   - config/keywords.json (스팸 키워드 목록)
#
# 판별 로직:
#   1차 키워드 매칭
#     └─ 매칭 없음 → 정상 댓글 (AI 호출 생략, 비용 절약)
#     └─ 매칭 있음 → 2차 AI 판별
#         └─ 확신도 >= 0.90 → 스팸 (자동 삭제)
#         └─ 확신도 0.70~0.89 + 키워드 매칭 → 스팸
#         └─ AI "스팸 아님" → 정상 (오삭제 방지)
#         └─ AI 호출 실패 → 정상으로 간주 (안전 우선)
#
# 안전장치:
#   - AI 실패 시 삭제 안 함 (False 반환)
#   - JSON 파싱 실패 시 텍스트 파싱 fallback
#   - 키워드 파일 누락 시 빈 목록으로 계속 동작
# ============================================================

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional
import google.generativeai as genai

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 판별 임계값 상수
# ──────────────────────────────────────────
SPAM_HIGH_CONFIDENCE   = 0.90  # 이상: 키워드 없어도 즉시 삭제
SPAM_MEDIUM_CONFIDENCE = 0.70  # 이상 + 키워드 매칭: 삭제


# ──────────────────────────────────────────
# 키워드 로드 (config/keywords.json)
# ──────────────────────────────────────────
def _load_spam_keywords() -> list[str]:
    """
    스팸 키워드 목록 로드
    안전장치: 파일 누락 또는 파싱 실패 시 빈 목록 반환 (봇 중단 방지)
    """
    try:
        # 이 파일 기준 상위 디렉토리의 config/keywords.json
        keywords_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(keywords_path, encoding="utf-8") as f:
            data = json.load(f)
        keywords = data.get("spam_keywords", [])
        logger.info(f"[spam] 키워드 {len(keywords)}개 로드 완료")
        return keywords
    except FileNotFoundError:
        logger.warning("[spam] keywords.json 파일 없음 — 키워드 필터 비활성화")
        return []
    except Exception as e:
        logger.error(f"[spam] keywords.json 로드 실패: {e}")
        return []


# 모듈 로드 시 1회만 읽음 (매 댓글마다 파일 IO 방지)
SPAM_KEYWORDS: list[str] = _load_spam_keywords()


# ──────────────────────────────────────────
# Gemini 클라이언트 초기화
# ──────────────────────────────────────────
def _get_gemini_model():
    """
    Gemini 1.5 Flash 모델 반환
    안전장치: API 키 누락 시 None 반환 (예외 미전파)
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("[spam] GEMINI_API_KEY 환경변수 누락")
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.0-flash")
    except Exception as e:
        logger.error(f"[spam] Gemini 초기화 실패: {e}")
        return None


# ──────────────────────────────────────────
# 1단계: 키워드 필터
# ──────────────────────────────────────────
def check_keyword_spam(text: str) -> Optional[str]:
    """
    1차 키워드 필터
    Returns: 매칭된 키워드 문자열 / None (매칭 없음)
    """
    text_lower = text.lower()
    for keyword in SPAM_KEYWORDS:
        if keyword.lower() in text_lower:
            logger.debug(f"[spam] 키워드 매칭: '{keyword}'")
            return keyword
    return None


# ──────────────────────────────────────────
# 2단계: Gemini AI 판별
# ──────────────────────────────────────────
def _parse_ai_response(response_text: str) -> tuple[bool, float]:
    """
    AI 응답 파싱 — JSON 우선, 실패 시 텍스트 패턴 fallback
    Returns: (is_spam: bool, confidence: float)
    """
    # JSON 형식 파싱 시도
    try:
        # 코드블록 제거 후 JSON 추출
        cleaned = re.sub(r"```(?:json)?", "", response_text).strip()
        data = json.loads(cleaned)
        is_spam   = bool(data.get("is_spam", False))
        confidence = float(data.get("confidence", 0.0))
        return is_spam, confidence
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    # Fallback: 텍스트 패턴 파싱
    is_spam    = "스팸" in response_text or "spam" in response_text.lower()
    conf_match = re.search(r"(\d+(?:\.\d+)?)\s*%?", response_text)
    confidence = float(conf_match.group(1)) / 100 if conf_match and float(conf_match.group(1)) > 1 else 0.5

    logger.debug(f"[spam] AI 응답 텍스트 파싱 — is_spam:{is_spam} conf:{confidence}")
    return is_spam, confidence


def check_ai_spam(comment_text: str, post_context: str = "") -> tuple[bool, float]:
    """
    2차 Gemini AI 스팸 판별
    Returns: (is_spam: bool, confidence: float 0.0~1.0)
    안전장치: 오류 시 (False, 0.0) 반환 — 삭제 안 함 원칙
    """
    model = _get_gemini_model()
    if not model:
        return False, 0.0

    prompt = f"""
당신은 한국 주식 투자 카페의 스팸 댓글 판별 전문가입니다.
아래 댓글이 스팸/광고인지 판별하고 JSON으로만 응답하세요.

게시글 맥락: {post_context[:200] if post_context else "없음"}
분석할 댓글: {comment_text[:500]}

판별 기준 (스팸):
- 오픈카톡방, 카카오톡 링크 유도
- 수익 보장, 투자 리딩방 광고
- 불법 도박, 성인 광고
- 출처 불명 주식 추천 링크

응답 형식 (JSON만, 다른 텍스트 없이):
{{"is_spam": true/false, "confidence": 0.0~1.0, "reason": "판별 이유 한 줄"}}
"""

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,   # 낮은 온도 = 일관된 판별
                max_output_tokens=150,
            ),
        )
        raw_text = response.text.strip()
        is_spam, confidence = _parse_ai_response(raw_text)
        logger.debug(f"[spam] AI 판별 — is_spam:{is_spam} confidence:{confidence:.2f}")
        return is_spam, confidence

    except Exception as e:
        logger.error(f"[spam] Gemini AI 호출 실패: {e}")
        return False, 0.0  # 실패 시 삭제 안 함


# ──────────────────────────────────────────
# 통합 판별 인터페이스
# ──────────────────────────────────────────
def is_spam(
    comment_text: str,
    post_context: str = "",
) -> tuple[bool, str]:
    """
    스팸 여부 최종 판별 — 외부에서 호출하는 단일 진입점
    Args:
        comment_text: 판별할 댓글 내용
        post_context: 게시글 맥락 (AI 정확도 향상용, 선택)
    Returns:
        (is_spam: bool, reason: str)
        - is_spam=True  → 삭제 대상
        - is_spam=False → 보존 대상
    """
    if not comment_text or not comment_text.strip():
        return False, "빈 댓글"

    # ── 1단계: 키워드 필터 ──
    matched_keyword = check_keyword_spam(comment_text)

    if not matched_keyword:
        # 키워드 없음 → AI 호출 생략 (비용 절약)
        return False, "키워드 없음 — 정상"

    # ── 2단계: AI 판별 ──
    ai_is_spam, confidence = check_ai_spam(comment_text, post_context)

    if not ai_is_spam:
        # AI가 스팸 아님 → 오삭제 방지 우선
        return False, f"AI 정상 판별 (conf:{confidence:.2f}) — 보존"

    if confidence >= SPAM_HIGH_CONFIDENCE:
        return True, f"AI 고확신 스팸 (conf:{confidence:.2f})"

    if confidence >= SPAM_MEDIUM_CONFIDENCE and matched_keyword:
        return True, f"AI 중확신 + 키워드 '{matched_keyword}' (conf:{confidence:.2f})"

    # 낮은 확신도 → 보존
    return False, f"확신도 부족 (conf:{confidence:.2f}) — 보존"
