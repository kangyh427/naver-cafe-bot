# ============================================================
# 파일명: spam_detector.py
# 경로:   kangyh427/naver_cafe_bot/src/spam_detector.py
# 역할:   스팸 댓글 판별 엔진
#         1차: 의심 닉네임 필터 (즉시 삭제)
#         2차: 키워드 필터 (빠른 차단)
#         3차: Gemini AI 판별 (정밀 분석)
#
# 작성일: 2026-03-09
# 수정일: 2026-03-10
# 버전:   v2.1
#
# [v2.1 — 2026-03-10]
#   기능 추가: 의심 닉네임 필터
#     - "알렉스강", "매니져", "매니저", "스텝" 등 관리자 사칭 닉네임 감지
#     - keywords.json → suspicious_nicknames 목록에서 로드
#     - 닉네임 매칭 시 AI 판별 없이 즉시 스팸 처리
#     - is_spam() 함수에 comment_author 파라미터 추가
#
# [v2.0 — 2026-03-10]
#   Bug Fix: Gemini 429 quota exceeded
#     - 지수 백오프 재시도, 분당 12회 자체 속도 제한 가드
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
# ──────────────────────────────────────────
_call_timestamps: list[float] = []
RATE_LIMIT_PER_MIN = 12
GEMINI_MAX_RETRY   = 2
GEMINI_RETRY_BASE  = 30


def _check_rate_limit() -> bool:
    """분당 호출 횟수 확인"""
    now = time.time()
    recent = [t for t in _call_timestamps if now - t < 60]
    _call_timestamps.clear()
    _call_timestamps.extend(recent)

    if len(recent) >= RATE_LIMIT_PER_MIN:
        oldest = min(recent)
        wait_sec = 60 - (now - oldest) + 1
        logger.warning(
            f"[spam] Gemini 분당 한도 도달 ({len(recent)}/{RATE_LIMIT_PER_MIN}) "
            f"→ {wait_sec:.0f}초 대기"
        )
        time.sleep(wait_sec)
        now2 = time.time()
        recent2 = [t for t in _call_timestamps if now2 - t < 60]
        return len(recent2) < RATE_LIMIT_PER_MIN

    return True


# ──────────────────────────────────────────
# 키워드 + 의심 닉네임 로드
# ──────────────────────────────────────────
def _load_keywords_config() -> dict:
    """keywords.json에서 스팸 키워드 + 의심 닉네임 로드"""
    try:
        kw_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(kw_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        logger.warning("[spam] keywords.json 없음 — 필터 비활성화")
        return {}
    except Exception as e:
        logger.error(f"[spam] keywords.json 로드 실패: {e}")
        return {}

_config = _load_keywords_config()
SPAM_KEYWORDS: list[str] = _config.get("spam_keywords", [])
SUSPICIOUS_NICKNAMES: list[str] = _config.get("suspicious_nicknames", [])

logger.info(
    f"[spam] 키워드 {len(SPAM_KEYWORDS)}개, "
    f"의심 닉네임 {len(SUSPICIOUS_NICKNAMES)}개 로드 완료"
)


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
# 0단계: 의심 닉네임 필터 (v2.1 신규)
# ──────────────────────────────────────────
def check_suspicious_nickname(author: str) -> Optional[str]:
    """
    관리자/스텝 사칭 닉네임 감지
    부분 일치(contains) 방식으로 검사
    Returns: 매칭된 닉네임 패턴 / None
    """
    if not author:
        return None
    author_lower = author.lower().strip()
    for nickname in SUSPICIOUS_NICKNAMES:
        if nickname.lower() in author_lower:
            return nickname
    return None


# ──────────────────────────────────────────
# 1단계: 키워드 필터
# ──────────────────────────────────────────
def check_keyword_spam(text: str) -> Optional[str]:
    """1차 키워드 필터 — Returns: 매칭된 키워드 / None"""
    text_lower = text.lower()
    for keyword in SPAM_KEYWORDS:
        if keyword.lower() in text_lower:
            return keyword
    return None


# ──────────────────────────────────────────
# 2단계: Gemini AI 판별
# ──────────────────────────────────────────
def _parse_ai_response(response_text: str) -> tuple[bool, float]:
    """AI 응답 파싱"""
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
    """2차 Gemini AI 스팸 판별"""
    model = _get_gemini_model()
    if not model:
        return False, 0.0

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
    comment_author: str = "",
) -> tuple[bool, str]:
    """
    스팸 여부 최종 판별 — 외부에서 호출하는 단일 진입점

    v2.1: comment_author 파라미터 추가
      - 의심 닉네임 감지 시 AI 판별 없이 즉시 스팸 처리

    Returns: (is_spam: bool, reason: str)
    """
    if not comment_text or not comment_text.strip():
        return False, "빈 댓글"

    # 0단계: 의심 닉네임 필터 (AI 없이 즉시 삭제)
    if comment_author:
        matched_nickname = check_suspicious_nickname(comment_author)
        if matched_nickname:
            logger.warning(
                f"[spam] 의심 닉네임 감지: '{comment_author}' "
                f"(패턴: '{matched_nickname}') → 즉시 삭제"
            )
            return True, f"의심 닉네임 '{matched_nickname}' 감지 — 관리자 사칭 의심"

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
