"""
spam_detector.py
Gemini AI + 키워드 기반 스팸 판별 엔진
- 1차: 키워드 필터링 (빠름)
- 2차: Gemini AI 판별 (정확도 향상)
- 확신도 90% 이상만 자동 삭제
"""

import os
import json
import re
import google.generativeai as genai
from typing import Tuple


class SpamDetector:
    def __init__(self):
        # Gemini API 설정
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")  # 무료 티어

        # 스팸 키워드 로드
        keywords_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "keywords.json"
        )
        with open(keywords_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.spam_keywords = config.get("spam_keywords", [])

        # 자동 삭제 확신도 임계값 (90% 이상만 삭제)
        self.AUTO_DELETE_THRESHOLD = 0.90

    def keyword_check(self, content: str) -> Tuple[bool, str]:
        """
        1차 키워드 필터링
        Returns: (is_spam, detected_keyword)
        """
        content_lower = content.lower()
        for keyword in self.spam_keywords:
            if keyword in content or keyword.lower() in content_lower:
                return True, keyword
        return False, ""

    async def ai_check(self, content: str) -> Tuple[float, str]:
        """
        2차 Gemini AI 스팸 판별
        Returns: (confidence, reason)
        """
        try:
            prompt = f"""당신은 한국 주식 투자 카페의 스팸/광고 댓글 탐지 전문가입니다.

아래 댓글이 스팸/광고/홍보성 내용인지 판단해주세요.

[스팸 기준]
- 유료/무료 리딩 서비스 홍보
- 카카오톡/텔레그램 초대 링크
- 수익 보장, 원금 보장 등 허위 광고
- 외부 사이트 링크 유도
- 종목 추천 유료 서비스 홍보

[댓글 내용]
{content}

[응답 형식 - JSON만 반환, 다른 텍스트 없이]
{{"is_spam": true/false, "confidence": 0.0~1.0, "reason": "판단 이유"}}"""

            response = self.model.generate_content(prompt)
            response_text = response.text.strip()

            # JSON 파싱
            # 코드 블록 제거
            response_text = re.sub(r"```json\n?|\n?```", "", response_text).strip()

            result = json.loads(response_text)
            confidence = float(result.get("confidence", 0.0))
            reason = result.get("reason", "AI 판별")

            return confidence, reason

        except Exception as e:
            print(f"[AI] Gemini 판별 오류: {e}")
            # AI 오류 시 삭제하지 않음 (안전 우선)
            return 0.0, f"AI 판별 오류: {str(e)}"

    async def is_spam(self, content: str) -> Tuple[bool, float, str, str]:
        """
        통합 스팸 판별
        Returns: (should_delete, confidence, reason, detected_keyword)
        """
        if not content or len(content.strip()) < 5:
            return False, 0.0, "내용 없음", ""

        # 1차: 키워드 필터
        keyword_match, detected_keyword = self.keyword_check(content)

        if keyword_match:
            print(f"[SPAM] 🚨 키워드 감지: '{detected_keyword}'")
            # 키워드 매칭 후 AI로 최종 확인
            confidence, reason = await self.ai_check(content)

            if confidence >= self.AUTO_DELETE_THRESHOLD:
                return True, confidence, reason, detected_keyword
            elif confidence >= 0.7:
                # AI가 70~90% 확신 → 키워드 매칭이므로 삭제
                return True, confidence, f"키워드+AI: {reason}", detected_keyword
            else:
                # AI가 스팸 아니라고 판단 → 보존 (오삭제 방지)
                print(f"[SPAM] AI가 스팸 아님으로 판단 (확신도: {confidence:.0%})")
                return False, confidence, "키워드 매칭이나 AI 스팸 아님", detected_keyword

        # 2차: 키워드 없어도 AI 검사 (교묘한 스팸)
        confidence, reason = await self.ai_check(content)

        if confidence >= self.AUTO_DELETE_THRESHOLD:
            print(f"[SPAM] 🚨 AI 스팸 감지 (확신도: {confidence:.0%})")
            return True, confidence, reason, ""

        return False, confidence, "정상 댓글", ""
