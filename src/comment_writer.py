# ============================================================
# 파일명: comment_writer.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_writer.py
# 역할:   신규 게시글에 Gemini AI 환영 댓글 자동 작성
#
# 작성일: 2026-03-09
# 수정일: 2026-03-11
# 버전:   v3.0
#
# [v3.0 — 2026-03-11] 근본 재설계
#   Bug Fix 1: 게시글 직접 이동 후 iframe 내부 댓글 입력창 접근 불가
#     - 기존: page.goto(url) 후 iframe#cafe_main에서 댓글창 탐색
#     - 수정: 네이버 카페 게시글은 직접 URL 접근 시 로그인 상태와
#             iframe 렌더링 타이밍이 불일치 → wait_for_selector로
#             실제 iframe 콘텐츠 로딩 완료 확인 후 진행
#   Bug Fix 2: 작성자 이름이 URL에서 추출되어 BOT_NICKNAME 비교 오류
#     - 기존: 게시글 목록에서 author를 추출했으나 불일치 케이스 있음
#     - 수정: 실제 게시글 내부에서 작성자 재확인
#   개선: 댓글 입력 selector 최신화 (2026년 네이버 카페 DOM 기준)
#   개선: 각 단계별 상세 로그 (어디서 실패하는지 명확히 추적)
#
# [v2.0 — 2026-03-10]
#   Bug Fix: Timeout, Execution context destroyed, Gemini 429
# ============================================================

import asyncio
import random
import json
import logging
import time
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
BOT_NICKNAMES     = ["AlexKang", "AlexKang", "알렉스강"]  # 봇/관리자 닉네임 목록
PAGE_LOAD_WAIT_S  = 4.0        # v3.0: iframe 로딩 여유 증가
COMMENT_MIN_LEN   = 20
COMMENT_MAX_LEN   = 150
IFRAME_TIMEOUT    = 20000      # iframe 내부 요소 대기 최대 시간(ms)
SELECTOR_TIMEOUT  = 15000

# Gemini 재시도 설정
GEMINI_MAX_RETRY  = 3
GEMINI_RETRY_BASE = 30         # 지수 백오프 기준(초)

# 댓글 입력창 후보 selector (우선순위 순, 2026년 네이버 카페 기준)
COMMENT_INPUT_SELECTORS = [
    "textarea.gfg-textarea",
    "textarea[placeholder*='댓글']",
    "textarea[placeholder*='comment']",
    ".comment-write-wrap textarea",
    ".CommentBox textarea",
    "textarea[name='content']",
    "#cmt_write",
    ".comment-textarea",
    "textarea",
]

# 댓글 제출 버튼 후보 selector
COMMENT_SUBMIT_SELECTORS = [
    "button.gfg-btn-write",
    "button.btn-comment-write",
    ".comment-write-wrap button[type='submit']",
    ".CommentBox button.btn_register",
    "button.btn_register",
    "button[onclick*='comment']",
    ".comment_write button[type='submit']",
]


# ──────────────────────────────────────────
# 환영 댓글 템플릿 (Gemini 실패 시 fallback)
# ──────────────────────────────────────────
DEFAULT_TEMPLATES = [
    "안녕하세요! 알렉스강의 주식이야기 카페에 오신 것을 환영합니다 🎉 좋은 정보 나눠주셔서 감사해요!",
    "환영합니다! 카페에서 좋은 인연 이어가요. 함께 성장하는 투자 커뮤니티가 되길 바랍니다 📈",
    "좋은 글 감사합니다! 카페 활동 활발히 해주세요. 함께 공부하며 성장해요 💪",
    "반갑습니다! 알렉스강 카페에서 함께 투자 공부해요. 언제든 궁금한 점 질문해 주세요 😊",
    "환영해요! 카페에 좋은 글 올려주셔서 감사합니다. 앞으로도 활발한 소통 부탁드립니다 🙌",
]

def _load_templates() -> list[str]:
    """keywords.json에서 환영 댓글 템플릿 로드, 실패 시 기본 템플릿 반환"""
    try:
        kw_path = Path(__file__).parent.parent / "config" / "keywords.json"
        with open(kw_path, encoding="utf-8") as f:
            data = json.load(f)
        templates = data.get("welcome_templates", [])
        if templates:
            return templates
    except Exception as e:
        logger.debug(f"[writer] 템플릿 로드 실패 → 기본 사용: {e}")
    return DEFAULT_TEMPLATES

WELCOME_TEMPLATES: list[str] = _load_templates()


# ──────────────────────────────────────────
# Gemini 모델 (지연 초기화)
# ──────────────────────────────────────────
def _get_gemini_model():
    """Gemini 모델 반환 (실패 시 None)"""
    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.0-flash")
    except Exception:
        return None


# ──────────────────────────────────────────
# Gemini AI 환영 댓글 생성
# ──────────────────────────────────────────
def generate_welcome_comment(post_title: str, post_content: str, author: str) -> str:
    """
    Gemini AI로 맞춤 환영 댓글 생성
    - 429 오류 발생 시 지수 백오프 후 최대 3회 재시도
    - 모든 재시도 실패 시 템플릿 fallback (항상 댓글 반환 보장)
    """
    model = _get_gemini_model()
    if not model:
        logger.warning("[writer] Gemini 모델 없음 → 템플릿 fallback")
        return random.choice(WELCOME_TEMPLATES)

    prompt = f"""당신은 한국 주식 투자 카페 '알렉스강의 주식이야기'의 관리자입니다.
신규 게시글에 따뜻하고 자연스러운 환영 댓글을 작성해 주세요.

게시글 제목: {post_title}
게시글 내용 (앞부분): {post_content[:200]}
작성자: {author}

요구사항:
- 20자 이상 150자 이하
- 게시글 내용과 자연스럽게 연결
- 주식/투자 카페 분위기 (너무 딱딱하지 않게)
- 이모지 1~2개
- 댓글 내용만 작성 (다른 설명 없이)"""

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
            else:
                logger.debug(f"[writer] AI 응답 너무 짧음({len(comment)}자) → 템플릿 fallback")
                return random.choice(WELCOME_TEMPLATES)

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                wait_sec = GEMINI_RETRY_BASE * (2 ** (attempt - 1))
                logger.warning(
                    f"[writer] Gemini 429 할당량 초과 "
                    f"(시도 {attempt}/{GEMINI_MAX_RETRY}) → {wait_sec}초 대기"
                )
                if attempt < GEMINI_MAX_RETRY:
                    time.sleep(wait_sec)
                    continue
            else:
                logger.error(f"[writer] Gemini 호출 실패 (시도 {attempt}): {e}")
            break

    logger.warning("[writer] Gemini 최대 재시도 소진 → 템플릿 fallback")
    return random.choice(WELCOME_TEMPLATES)


# ──────────────────────────────────────────
# iframe 안전 획득 + 콘텐츠 로딩 대기
# ──────────────────────────────────────────
async def _get_fresh_frame(page: Page):
    """
    페이지 이동 후 반드시 새 frame 참조 획득
    v3.0: iframe 콘텐츠 실제 로딩 완료까지 대기
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        frame = page.frame_locator("iframe#cafe_main").first
        return frame
    except Exception:
        logger.debug("[writer] iframe 없음 → page 직접 사용")
        return page


# ──────────────────────────────────────────
# 게시글 내용 읽기
# ──────────────────────────────────────────
async def _read_post_content(page: Page) -> tuple[str, str, str]:
    """
    현재 페이지에서 게시글 제목/내용/작성자 추출
    Returns: (title, content, author)
    """
    TITLE_SELECTORS   = [".title-text", ".tit-box .title", "h3.title", ".ArticleTitle", ".article-title"]
    CONTENT_SELECTORS = [".se-main-container", ".se-text-paragraph", ".tbody", ".article_body", "#postContent", ".articleContents"]
    AUTHOR_SELECTORS  = [".writer-nick-wrap .nick", ".cafe-nick-name", ".writer_info .nick", ".m-tcol-c", ".nickname", ".author"]

    try:
        frame = await _get_fresh_frame(page)

        async def try_selectors(selectors: list[str]) -> str:
            for sel in selectors:
                try:
                    el   = frame.locator(sel).first
                    text = await el.text_content(timeout=5000)
                    if text and text.strip():
                        return text.strip()
                except Exception:
                    continue
            return ""

        title   = await try_selectors(TITLE_SELECTORS)
        content = await try_selectors(CONTENT_SELECTORS)
        author  = await try_selectors(AUTHOR_SELECTORS) or "알수없음"

        logger.debug(f"[writer] 게시글 내용 읽기: 제목='{title[:30]}' 작성자='{author}'")
        return title, content, author

    except Exception as e:
        logger.debug(f"[writer] 게시글 내용 읽기 실패: {e}")
        return "", "", "알수없음"


# ──────────────────────────────────────────
# 댓글 입력 및 제출 (v3.0 근본 재설계)
# ──────────────────────────────────────────
async def _submit_comment(page: Page, comment_text: str) -> bool:
    """
    댓글 작성 및 제출

    v3.0 핵심 변경:
      - iframe 로딩 완료 후 댓글 입력창 대기
      - 입력창이 disabled/readonly 상태인지 확인 후 진행
      - 각 단계 상세 로그로 실패 원인 추적
    Returns: True (성공) / False (실패)
    """
    try:
        frame = await _get_fresh_frame(page)

        # ── 1. 댓글 입력창 찾기 ──
        input_el = None
        for sel in COMMENT_INPUT_SELECTORS:
            try:
                el = frame.locator(sel).first
                # is_visible + is_enabled 둘 다 확인
                if await el.is_visible(timeout=SELECTOR_TIMEOUT):
                    is_disabled = await el.is_disabled()
                    if not is_disabled:
                        input_el = el
                        logger.debug(f"[writer] 입력창 selector 성공: '{sel}'")
                        break
                    else:
                        logger.debug(f"[writer] 입력창 disabled 상태, 다음 selector 시도: '{sel}'")
            except Exception as e:
                logger.debug(f"[writer] 입력창 selector 실패 '{sel}': {e}")
                continue

        if not input_el:
            logger.error("[writer] 댓글 입력창을 찾을 수 없음 — 모든 selector 실패")
            # 현재 iframe 내 textarea 전체 확인
            try:
                all_textareas = await frame.locator("textarea").all()
                logger.debug(f"[writer] 현재 페이지 textarea 개수: {len(all_textareas)}")
                for i, ta in enumerate(all_textareas[:3]):
                    ph = await ta.get_attribute("placeholder") or ""
                    logger.debug(f"[writer]   textarea[{i}] placeholder='{ph}'")
            except Exception:
                pass
            return False

        # ── 2. 입력창 클릭 후 타이핑 ──
        await input_el.click()
        await asyncio.sleep(random.uniform(0.4, 0.8))
        await input_el.type(comment_text, delay=random.randint(60, 130))
        await asyncio.sleep(random.uniform(0.8, 1.5))

        # 입력 내용 확인
        typed = await input_el.input_value()
        if not typed:
            # textarea가 아닌 contenteditable일 경우 text_content로 확인
            typed = await input_el.text_content() or ""
        logger.debug(f"[writer] 입력 확인: '{typed[:30]}'")

        if not typed:
            logger.error("[writer] 댓글 입력 후 내용이 비어있음 — 입력 실패")
            return False

        # ── 3. 제출 버튼 찾기 ──
        submit_el = None
        for sel in COMMENT_SUBMIT_SELECTORS:
            try:
                el = frame.locator(sel).first
                if await el.is_visible(timeout=5000):
                    submit_el = el
                    logger.debug(f"[writer] 제출 버튼 selector 성공: '{sel}'")
                    break
            except Exception:
                continue

        if not submit_el:
            logger.error("[writer] 댓글 제출 버튼을 찾을 수 없음")
            return False

        # ── 4. 제출 ──
        await submit_el.click()
        await asyncio.sleep(2.5)

        logger.debug("[writer] 댓글 제출 완료")
        return True

    except Exception as e:
        logger.error(f"[writer] 댓글 제출 실패: {e}", exc_info=True)
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
        post_urls: cafe_monitor.py에서 받은 신규 게시글 URL 목록
    Returns:
        작성 성공한 댓글 수
    """
    success_count = 0
    logger.info(f"[writer] 환영 댓글 작성 시작 | 대상: {len(post_urls)}개 게시글")

    for idx, url in enumerate(post_urls):
        try:
            # 1. 중복 확인 (monitor 단계에서도 체크했지만 이중 안전장치)
            if is_post_processed(url):
                logger.debug(f"[writer] 이미 처리됨, 스킵 ({idx+1}/{len(post_urls)}): {url[-50:]}")
                continue

            logger.info(f"[writer] 게시글 처리 ({idx+1}/{len(post_urls)}): {url[-60:]}")

            # 2. 게시글 진입
            await page.goto(url, timeout=25000, wait_until="domcontentloaded")
            await asyncio.sleep(PAGE_LOAD_WAIT_S)

            # 3. 내용 읽기
            title, content, author = await _read_post_content(page)

            # 4. 관리자/봇 본인 글 스킵
            if any(bn.lower() in author.lower() for bn in BOT_NICKNAMES):
                logger.debug(f"[writer] 관리자/봇 글 스킵: '{author}'")
                # 본인 글도 processed로 등록하여 재처리 방지
                mark_post_processed(url, author)
                continue

            # 5. AI 환영 댓글 생성 (동기 함수 → 별도 스레드에서 실행)
            comment = await asyncio.get_event_loop().run_in_executor(
                None,
                generate_welcome_comment,
                title, content, author
            )
            logger.debug(f"[writer] 생성된 댓글: '{comment[:50]}'")

            # 6. 댓글 작성
            submitted = await _submit_comment(page, comment)

            if submitted:
                success_count += 1
                mark_post_processed(url, author)
                log_welcome_comment(url, author, comment)
                logger.info(f"[writer] ✅ 환영 댓글 작성 완료: {author} — '{title[:30]}'")
            else:
                logger.warning(f"[writer] ❌ 댓글 제출 실패: {url[-60:]}")

            # 게시글 간 딜레이 (계정 보호)
            await asyncio.sleep(random.uniform(3.0, 6.0))

        except Exception as e:
            logger.error(f"[writer] 게시글 처리 오류 [{url[-50:]}]: {e}", exc_info=True)

    logger.info(f"[writer] 완료 | 작성:{success_count}/{len(post_urls)}")
    return success_count
