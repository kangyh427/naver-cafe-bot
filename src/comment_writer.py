# ============================================================
# 파일명: comment_writer.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_writer.py
# 역할:   신규 게시글에 Gemini AI 환영 댓글 자동 작성
#
# 작성일: 2026-03-09
# 수정일: 2026-03-12
# 버전:   v5.0
#
# [v5.0 — 2026-03-12] 근본 수정: comment_dom.py 연동
#   원인 확정:
#     네이버 카페 댓글창은 iframe#cafe_main 내부에 존재함
#     v4.0에서 "iframe 없이 page 직접 사용"으로 잘못 변경하여
#     textarea를 전혀 찾지 못한 채 무음 실패 반복
#   수정:
#     - _submit_comment() 제거 → comment_dom.submit_comment() 위임
#     - _read_post_content() 제거 → comment_dom.read_post_content() 위임
#     - 중복 selector 정의 전부 제거 (comment_dom.py가 단일 관리)
#     - run_comment_writer() 내 goto 후 대기 시간 충분히 확보
#   안전장치:
#     - comment_dom import 실패 시 즉시 명확한 오류 메시지
#     - goto 후 networkidle 대기 (댓글창 늦게 렌더링 대응)
#     - 연속 실패 3회 시 조기 종료 (무한 루프 방지)
#
# [v4.0 — 2026-03-11] (❌ 잘못된 방향 — iframe 제거가 원인)
# [v3.0 — 2026-03-10] 지수백오프 재시도
# [v1.0 — 2026-03-09] 최초 작성
# ============================================================

import asyncio
import random
import json
import logging
import time
from pathlib import Path

import google.generativeai as genai
from playwright.async_api import Page

# ── 핵심: DOM 접근은 comment_dom 전담 ──
from comment_dom import read_post_content, submit_comment
from supabase_logger import is_post_processed, mark_post_processed, log_welcome_comment

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
BOT_NICKNAMES     = ["AlexKang", "알렉스강"]
PAGE_LOAD_WAIT_S  = 6.0          # v5.1: fe.naver.com U_cbox 초기화 대기 (4.0→6.0초)
COMMENT_MIN_LEN   = 20
COMMENT_MAX_LEN   = 150
MAX_CONSECUTIVE_FAILURES = 3     # 연속 실패 한도 (안전장치)

GEMINI_MAX_RETRY  = 3
GEMINI_RETRY_BASE = 30           # 초


# ──────────────────────────────────────────
# 템플릿 로드
# ──────────────────────────────────────────
DEFAULT_TEMPLATES = [
    "안녕하세요! 알렉스강의 주식이야기 카페에 오신 것을 환영합니다 🎉 좋은 정보 나눠주셔서 감사해요!",
    "환영합니다! 카페에서 좋은 인연 이어가요. 함께 성장하는 투자 커뮤니티가 되길 바랍니다 📈",
    "좋은 글 감사합니다! 카페 활동 활발히 해주세요. 함께 공부하며 성장해요 💪",
    "반갑습니다! 알렉스강 카페에서 함께 투자 공부해요. 언제든 궁금한 점 질문해 주세요 😊",
    "환영해요! 카페에 좋은 글 올려주셔서 감사합니다. 앞으로도 활발한 소통 부탁드립니다 🙌",
]

def _load_templates() -> list[str]:
    try:
        kw_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(kw_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("welcome_templates", []) or DEFAULT_TEMPLATES
    except Exception:
        return DEFAULT_TEMPLATES

WELCOME_TEMPLATES: list[str] = _load_templates()


# ──────────────────────────────────────────
# Gemini AI 댓글 생성
# ──────────────────────────────────────────
def _get_gemini_model():
    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[writer] GEMINI_API_KEY 없음 → 기본 템플릿 사용")
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.0-flash")
    except Exception as e:
        logger.error(f"[writer] Gemini 초기화 실패: {e}")
        return None


def generate_welcome_comment(post_title: str, post_content: str, author: str) -> str:
    """
    Gemini AI로 게시글 맞춤 환영 댓글 생성
    실패 시 기본 템플릿 랜덤 반환 (봇 중단 방지)
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

    for attempt in range(1, GEMINI_MAX_RETRY + 1):
        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.8,
                    max_output_tokens=200,
                ),
            )
            comment = response.text.strip()
            if COMMENT_MIN_LEN <= len(comment) <= COMMENT_MAX_LEN:
                return comment
            elif len(comment) > COMMENT_MAX_LEN:
                return comment[:COMMENT_MAX_LEN]
            return random.choice(WELCOME_TEMPLATES)

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                wait_sec = GEMINI_RETRY_BASE * (2 ** (attempt - 1))
                logger.warning(
                    f"[writer] Gemini 429 → {wait_sec}초 대기 "
                    f"({attempt}/{GEMINI_MAX_RETRY})"
                )
                if attempt < GEMINI_MAX_RETRY:
                    time.sleep(wait_sec)
                    continue
            else:
                logger.error(f"[writer] Gemini 실패 (시도 {attempt}): {e}")
            break

    return random.choice(WELCOME_TEMPLATES)


# ──────────────────────────────────────────
# 메인 실행 함수
# ──────────────────────────────────────────
async def run_comment_writer(page: Page, post_urls: list[str]) -> int:
    """
    신규 게시글 목록에 환영 댓글 작성
    main.py에서 호출하는 단일 진입점

    v5.0 핵심 변경:
      - _read_post_content() → comment_dom.read_post_content()
      - _submit_comment()    → comment_dom.submit_comment()
      - networkidle 대기로 댓글창 렌더링 완료 보장
      - 연속 실패 3회 시 조기 종료 (무한 루프 안전장치)
    """
    success_count      = 0
    consecutive_fails  = 0
    logger.info(f"[writer] 시작 | 대상: {len(post_urls)}개")

    for idx, url in enumerate(post_urls):
        # 연속 실패 안전장치
        if consecutive_fails >= MAX_CONSECUTIVE_FAILURES:
            logger.error(
                f"[writer] 연속 실패 {consecutive_fails}회 → 조기 종료 "
                f"(DOM/로그인 문제 의심)"
            )
            break

        try:
            # 1. 중복 처리 확인
            if is_post_processed(url):
                logger.debug(f"[writer] 이미 처리됨 ({idx+1}/{len(post_urls)}): {url[-50:]}")
                continue

            logger.info(f"[writer] 처리 ({idx+1}/{len(post_urls)}): {url[-60:]}")

            # 2. 게시글 이동 — networkidle로 댓글창 완전 로드 보장
            try:
                await page.goto(url, timeout=30000, wait_until="networkidle")
            except Exception:
                # networkidle 타임아웃은 흔함 — domcontentloaded로 폴백
                await page.goto(url, timeout=25000, wait_until="domcontentloaded")

            # iframe 렌더링 충분히 대기
            await asyncio.sleep(PAGE_LOAD_WAIT_S)

            # 3. 게시글 내용 읽기 (comment_dom 위임)
            title, content, author = await read_post_content(page)

            # 4. 관리자/봇 본인 글 스킵
            if any(bn.lower() in author.lower() for bn in BOT_NICKNAMES):
                logger.debug(f"[writer] 관리자 글 스킵: '{author}'")
                mark_post_processed(url, author)
                consecutive_fails = 0
                continue

            # 5. AI 댓글 생성 (동기 함수 → executor에서 실행)
            comment = await asyncio.get_event_loop().run_in_executor(
                None, generate_welcome_comment, title, content, author
            )
            logger.info(f"[writer] 생성된 댓글: '{comment[:50]}'")

            # 6. 댓글 제출 (comment_dom 위임 — iframe Frame 객체 방식)
            submitted = await submit_comment(page, comment)

            if submitted:
                success_count     += 1
                consecutive_fails  = 0
                mark_post_processed(url, author)
                log_welcome_comment(url, author, comment)
                logger.info(f"[writer] ✅ 완료: {author} — '{title[:30]}'")
            else:
                consecutive_fails += 1
                logger.warning(
                    f"[writer] ❌ 실패 ({consecutive_fails}/{MAX_CONSECUTIVE_FAILURES}): "
                    f"{url[-60:]}"
                )

            # 게시글 간 랜덤 딜레이 (봇 탐지 회피)
            await asyncio.sleep(random.uniform(4.0, 7.0))

        except Exception as e:
            consecutive_fails += 1
            logger.error(f"[writer] 오류 [{url[-50:]}]: {e}", exc_info=True)

    logger.info(
        f"[writer] 완료 | 성공:{success_count}/{len(post_urls)} "
        f"연속실패:{consecutive_fails}"
    )
    return success_count
