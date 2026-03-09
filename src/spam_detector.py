# ============================================================
# 파일명: spam_detector.py
# 경로:   kangyh427/naver_cafe_bot/src/spam_detector.py
# 역할:   스팸 댓글 2단계 판별 엔진
#         1차: 키워드 필터 (빠른 차단)
#         2차: Gemini AI 판별 (정밀 분석)
#
# 작성일: 2026-03-09
# 수정일: 2026-03-10
# 버전:   v2.0
#
# [v2.0 — 2026-03-10]
#   Bug Fix: Gemini 429 quota exceeded
#     - 원인: Free Tier 분당/일당 호출 한도 초과
#     - 수정1: 지수 백오프 재시도 (최대 2회, 30s/60s 대기)
#     - 수정2: 모듈 레벨 호출 카운터 — 분당 12회 초과 시 AI 생략
#              (Free Tier 한도 15회/분에서 여유 3회 보존)
#     - 수정3: 429 발생 시 즉시 False 반환 (삭제 안 함 원칙 유지)
#
# [v1.0 — 2026-03-09]
#   최초 작성
# ============================================================

import os
import re
import json
import time
import logging
from pathlib import Path
from typing import Optional
import google.generativeai as genai

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 판별 임계값
# ──────────────────────────────────────────
SPAM_HIGH_CONFIDENCE   = 0.90
SPAM_MEDIUM_CONFIDENCE = 0.70

# ──────────────────────────────────────────
# Gemini 호출 속도 제한 가드
# (Free Tier: 15 req/min → 분당 12회로 자체 제한)
# ──────────────────────────────────────────
_call_timestamps: list[float] = []   # 최근 호출 시각 기록
RATE_LIMIT_PER_MIN = 12              # 자체 제한 (Free Tier 15 중 여유 3 확보)
GEMINI_MAX_RETRY   = 2               # 429 재시도 횟수
GEMINI_RETRY_BASE  = 30              # 지수 백오프 기준 초


def _check_rate_limit() -> bool:
    """
    분당 호출 횟수 확인
    Returns: True (호출 가능) / False (한도 초과, 대기 필요)
    """
    now = time.time()
    # 1분 이내 호출만 유지
    recent = [t for t in _call_timestamps if now - t < 60]
    _call_timestamps.clear()
    _call_timestamps.extend(recent)

    if len(recent) >= RATE_LIMIT_PER_MIN:
        oldest = min(recent)
        wait_sec = 60 - (now - oldest) + 1
        logger.warning(
            f"[spam] Gemini 분당 한도 도달 ({len(recent)}/{RATE_LIMIT_PER_MIN}) "
            f"→ {wait_sec:.0f}초 대기 후 재시도"
        )
        time.sleep(wait_sec)
        # 대기 후 재확인
        now2 = time.time()
        recent2 = [t for t in _call_timestamps if now2 - t < 60]
        return len(recent2) < RATE_LIMIT_PER_MIN

    return True


# ──────────────────────────────────────────
# 키워드 로드
# ──────────────────────────────────────────
def _load_spam_keywords() -> list[str]:
    try:
        kw_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(kw_path, encoding="utf-8") as f:
            data = json.load(f)
        keywords = data.get("spam_keywords", [])
        logger.info(f"[spam] 키워드 {len(keywords)}개 로드 완료")
        return keywords
    except FileNotFoundError:
        logger.warning("[spam] keywords.json 없음 — 키워드 필터 비활성화")
        return []
    except Exception as e:
        logger.error(f"[spam] keywords.json 로드 실패: {e}")
        return []

SPAM_KEYWORDS: list[str] = _load_spam_keywords()


# ──────────────────────────────────────────
# Gemini 클라이언트
# ──────────────────────────────────────────
def _get_gemini_model():
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
    Returns: 매칭된 키워드 / None
    """
    text_lower = text.lower()
    for keyword in SPAM_KEYWORDS:
        if keyword.lower() in text_lower:
            return keyword
    return None


# ──────────────────────────────────────────
# 2단계: Gemini AI 판별 (지수 백오프 재시도)
# ──────────────────────────────────────────
def _parse_ai_response(response_text: str) -> tuple[bool, float]:
    """AI 응답 파싱 — JSON 우선, 실패 시 텍스트 fallback"""
    try:
        cleaned = re.sub(r"```(?:json)?", "", response_text).strip()
        data = json.loads(cleaned)
        return bool(data.get("is_spam", False)), float(data.get("confidence", 0.0))
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    is_spam    = "스팸" in response_text or "spam" in response_text.lower()
    conf_match = re.search(r"(\d+(?:\.\d+)?)\s*%?", response_text)
    confidence = float(conf_match.group(1)) / 100 if conf_match and float(conf_match.group(1)) > 1 else 0.5
    return is_spam, confidence


def check_ai_spam(comment_text: str, post_context: str = "") -> tuple[bool, float]:
    """
    2차 Gemini AI 스팸 판별
    - 분당 호출 한도 초과 시 자동 대기
    - 429 발생 시 지수 백오프 재시도 (최대 2회)
    Returns: (is_spam: bool, confidence: float)
    안전장치: 오류 시 (False, 0.0) — 삭제 안 함 원칙
    """
    model = _get_gemini_model()
    if not model:
        return False, 0.0

    # 분당 속도 제한 확인
    if not _check_rate_limit():
        logger.warning("[spam] 속도 제한 대기 후에도 한도 초과 → 정상으로 처리")
        return False, 0.0

    prompt = f"""당신은 한국 주식 투자 카페의 스팸 댓글 판별 전문가입니다.
아래 댓글이 스팸/광고인지 판별하고 JSON으로만 응답하세요.

게시글 맥락: {post_context[:150] if post_context else "없음"}
분석할 댓글: {comment_text[:300]}

스팸 기준: 오픈카톡/텔레그램 유도, 수익 보장, 리딩방 광고, 불법 링크

JSON만 반환 (다른 텍스트 없이):
{{"is_spam": true/false, "confidence": 0.0~1.0, "reason": "이유"}}"""

    for attempt in range(1, GEMINI_MAX_RETRY + 1):
        try:
            # 호출 시각 기록
            _call_timestamps.append(time.time())

            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=100,
                ),
            )
            is_spam_flag, confidence = _parse_ai_response(response.text.strip())
            logger.debug(f"[spam] AI 판별 — is_spam:{is_spam_flag} conf:{confidence:.2f}")
            return is_spam_flag, confidence

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                wait_sec = GEMINI_RETRY_BASE * (2 ** (attempt - 1))
                logger.warning(
                    f"[spam] Gemini 429 (시도 {attempt}/{GEMINI_MAX_RETRY}) "
                    f"→ {wait_sec}초 대기"
                )
                if attempt < GEMINI_MAX_RETRY:
                    time.sleep(wait_sec)
                    continue
                else:
                    logger.error("[spam] Gemini 최대 재시도 소진 → 정상으로 처리")
            else:
                logger.error(f"[spam] Gemini 호출 실패 (시도 {attempt}): {e}")
            break

    return False, 0.0


# ──────────────────────────────────────────
# 통합 판별 인터페이스
# ──────────────────────────────────────────
def is_spam(
    comment_text: str,
    post_context: str = "",
) -> tuple[bool, str]:
    """
    스팸 여부 최종 판별 — 외부에서 호출하는 단일 진입점
    Returns: (is_spam: bool, reason: str)
    """
    if not comment_text or not comment_text.strip():
        return False, "빈 댓글"

    # 1단계: 키워드 필터
    matched_keyword = check_keyword_spam(comment_text)
    if not matched_keyword:
        return False, "키워드 없음 — 정상"

    # 2단계: AI 판별
    ai_is_spam, confidence = check_ai_spam(comment_text, post_context)

    if not ai_is_spam:
        return False, f"AI 정상 판별 (conf:{confidence:.2f}) — 보존"

    if confidence >= SPAM_HIGH_CONFIDENCE:
        return True, f"AI 고확신 스팸 (conf:{confidence:.2f})"

    if confidence >= SPAM_MEDIUM_CONFIDENCE and matched_keyword:
        return True, f"AI 중확신 + 키워드 '{matched_keyword}' (conf:{confidence:.2f})"

    return False, f"확신도 부족 (conf:{confidence:.2f}) — 보존"
