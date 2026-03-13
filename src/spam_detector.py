# ============================================================
# 파일명: spam_detector.py
# 경로:   kangyh427/naver-cafe-bot/src/spam_detector.py
# 역할:   스팸 댓글 판별 엔진
#         0단계: 사칭 닉네임 필터 (즉시 삭제)
#         1단계: 키워드 필터 (빠른 차단)
#         2단계: Gemini AI 판별 (정밀 분석)
#
# 작성일: 2026-03-09
# 수정일: 2026-03-13
# 버전:   v3.0
#
# [v3.0 — 2026-03-13] 사칭 닉네임 감지 정밀화
#   개선 1: 단순 contains → 정규식(regex) 기반 패턴 매칭으로 변경
#           "알렉스강 3월 안내", "알렉스강관리자" 등 변형 패턴 모두 포착
#   개선 2: IMPERSONATION_PATTERNS (정규식 리스트) 하드코딩 추가
#           keywords.json 로드 실패 시에도 핵심 사칭 패턴은 항상 동작
#   개선 3: 매칭 결과에 패턴 종류(contains/regex) 명시 → 로그 분석 용이
#
# [v2.1 — 2026-03-10] 의심 닉네임 필터 추가
# [v2.0 — 2026-03-10] Gemini 429 quota 대응 (지수 백오프)
# [v1.0 — 2026-03-09] 최초 작성
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
_call_timestamps: list = []
RATE_LIMIT_PER_MIN = 5
GEMINI_MAX_RETRY   = 3
GEMINI_RETRY_BASE  = 30


def _check_rate_limit() -> bool:
    now    = time.time()
    recent = [t for t in _call_timestamps if now - t < 60]
    _call_timestamps.clear()
    _call_timestamps.extend(recent)

    if len(recent) >= RATE_LIMIT_PER_MIN:
        oldest   = min(recent)
        wait_sec = 60 - (now - oldest) + 1
        logger.warning(
            f"[spam] Gemini 분당 한도 ({len(recent)}/{RATE_LIMIT_PER_MIN}) "
            f"→ {wait_sec:.0f}초 대기"
        )
        time.sleep(wait_sec)
        now2    = time.time()
        recent2 = [t for t in _call_timestamps if now2 - t < 60]
        return len(recent2) < RATE_LIMIT_PER_MIN

    return True


# ──────────────────────────────────────────
# v3.0: 하드코딩 사칭 정규식 패턴
# (keywords.json 로드 실패해도 항상 동작하는 안전장치)
# ──────────────────────────────────────────
IMPERSONATION_PATTERNS = [
    r"알렉스\s*강",          # "알렉스강", "알렉스 강", "알렉스강관리자", "알렉스강 3월 안내" 등
    r"alex\s*kang",          # "alexkang", "alex kang" 등 영문 변형
    r"운영\s*자",            # "운영자", "운영 자"
    r"관리\s*자",            # "관리자", "관리 자"
    r"매니\s*[져저]",        # "매니져", "매니저", "매니 저"
    r"스\s*텝",              # "스텝", "스 텝"
    r"스\s*태\s*프",         # "스태프", "스 태프"
    r"부\s*매니\s*[져저]",   # "부매니저", "부매니져"
    r"副\s*매니\s*[져저]",   # "副매니저"
]

# 컴파일된 패턴 (한 번만 컴파일, 대소문자 무시)
_COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in IMPERSONATION_PATTERNS
]


# ──────────────────────────────────────────
# 키워드 + 의심 닉네임 로드
# ──────────────────────────────────────────
def _load_keywords_config() -> dict:
    try:
        kw_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(kw_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        logger.warning("[spam] keywords.json 없음 — 기본 패턴으로만 동작")
        return {}
    except Exception as e:
        logger.error(f"[spam] keywords.json 로드 실패: {e}")
        return {}

_config = _load_keywords_config()
SPAM_KEYWORDS: list        = _config.get("spam_keywords", [])
SUSPICIOUS_NICKNAMES: list = _config.get("suspicious_nicknames", [])

logger.info(
    f"[spam] 키워드 {len(SPAM_KEYWORDS)}개, "
    f"의심 닉네임 {len(SUSPICIOUS_NICKNAMES)}개, "
    f"사칭 정규식 패턴 {len(IMPERSONATION_PATTERNS)}개 로드 완료"
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
# 0단계: 사칭 닉네임 필터 (v3.0 정규식 강화)
# ──────────────────────────────────────────
def check_suspicious_nickname(author: str) -> Optional[str]:
    """
    관리자/운영자/스텝 사칭 닉네임 감지

    v3.0 변경:
      단순 contains → 정규식 우선 탐색 후 contains 폴백
      → "알렉스강 3월 안내", "알렉스강관리자" 등 변형 패턴도 감지

    Returns: 감지된 패턴 설명 / None
    """
    if not author:
        return None

    author_str = author.strip()

    # 1차: 정규식 패턴 매칭 (변형 포함)
    for pattern_str, compiled in zip(IMPERSONATION_PATTERNS, _COMPILED_PATTERNS):
        if compiled.search(author_str):
            logger.debug(
                f"[spam] 사칭 닉네임 정규식 매칭: "
                f"'{author_str}' → 패턴='{pattern_str}'"
            )
            return f"regex:{pattern_str}"

    # 2차: keywords.json suspicious_nicknames contains 매칭 (보조)
    author_lower = author_str.lower()
    for nickname in SUSPICIOUS_NICKNAMES:
        if nickname.lower() in author_lower:
            logger.debug(
                f"[spam] 사칭 닉네임 contains 매칭: "
                f"'{author_str}' → 키워드='{nickname}'"
            )
            return f"contains:{nickname}"

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
def _parse_ai_response(response_text: str) -> tuple:
    try:
        cleaned = re.sub(r"```(?:json)?", "", response_text).strip()
        data    = json.loads(cleaned)
        return bool(data.get("is_spam", False)), float(data.get("confidence", 0.0))
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    is_spam_flag = "스팸" in response_text or "spam" in response_text.lower()
    conf_match   = re.search(r"(\d+(?:\.\d+)?)\s*%?", response_text)
    confidence   = (
        float(conf_match.group(1)) / 100
        if conf_match and float(conf_match.group(1)) > 1
        else 0.5
    )
    return is_spam_flag, confidence


def check_ai_spam(comment_text: str, post_context: str = "") -> tuple:
    """2차 Gemini AI 스팸 판별"""
    model = _get_gemini_model()
    if not model:
        return False, 0.0

    if not _check_rate_limit():
        logger.warning("[spam] 속도 제한 초과 → 정상으로 처리")
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
) -> tuple:
    """
    스팸 여부 최종 판별 — 외부에서 호출하는 단일 진입점

    판별 순서:
      0단계: 사칭 닉네임 감지 (정규식 + contains) → 즉시 True
      1단계: 키워드 필터 → 미탐지 시 정상(False) 반환
      2단계: AI 판별 → 확신도 기반 최종 결정

    Returns: (is_spam: bool, reason: str)
    """
    if not comment_text or not comment_text.strip():
        return False, "빈 댓글"

    # ── 0단계: 사칭 닉네임 감지 (AI 없이 즉시 처리) ──
    if comment_author:
        matched = check_suspicious_nickname(comment_author)
        if matched:
            reason_type = "정규식" if matched.startswith("regex:") else "키워드"
            pattern_val = matched.split(":", 1)[1] if ":" in matched else matched
            logger.warning(
                f"[spam] ⚠️ 사칭 닉네임 감지 ({reason_type}): "
                f"'{comment_author}' → 패턴='{pattern_val}'"
            )
            return True, f"사칭 닉네임 감지({reason_type}): '{pattern_val}' — 관리자/운영자 사칭"

    # ── 1단계: 키워드 필터 ──
    matched_keyword = check_keyword_spam(comment_text)
    if not matched_keyword:
        return False, "키워드 없음 — 정상"

    # ── 2단계: AI 판별 ──
    ai_is_spam, confidence = check_ai_spam(comment_text, post_context)

    if not ai_is_spam:
        return False, f"AI 정상 판별 (conf:{confidence:.2f}) — 보존"

    if confidence >= SPAM_HIGH_CONFIDENCE:
        return True, f"AI 고확신 스팸 (conf:{confidence:.2f})"

    if confidence >= SPAM_MEDIUM_CONFIDENCE and matched_keyword:
        return True, f"AI 중확신 + 키워드 '{matched_keyword}' (conf:{confidence:.2f})"

    return False, f"확신도 부족 (conf:{confidence:.2f}) — 보존"
