# ============================================================
# 파일명: comment_writer.py
# 경로:   kangyh427/naver_cafe_bot/src/comment_writer.py
# 역할:   신규 게시글에 Gemini AI 환영 댓글 자동 작성
#
# 작성일: 2026-03-09
# 수정일: 2026-03-11
# 버전:   v4.0
#
# [v4.0 — 2026-03-11] 실제 DOM 직접 확인 기반 selector 확정
#   핵심 발견 (크롬 개발자도구 직접 확인):
#     - 댓글창은 iframe 안이 아닌 메인 페이지에 직접 렌더링
#     - 입력창: textarea.comment_inbox_text
#     - 컨테이너: div.CommentWriter > div.comment_inbox
#     - 제출버튼: div.register_box 안의 button
#   수정:
#     - iframe 탐색 로직 완전 제거 → page 직접 사용
#     - selector 실제 DOM 기반으로 확정
#     - 제출 후 입력창 초기화 여부로 성공 검증
# ============================================================

import asyncio
import random
import json
import logging
import time
from pathlib import Path

import google.generativeai as genai
from playwright.async_api import Page

from supabase_logger import is_post_processed, mark_post_processed, log_welcome_comment

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
BOT_NICKNAMES    = ["AlexKang", "알렉스강"]
PAGE_LOAD_WAIT_S = 3.0
COMMENT_MIN_LEN  = 20
COMMENT_MAX_LEN  = 150
ACTION_TIMEOUT   = 10000

GEMINI_MAX_RETRY  = 3
GEMINI_RETRY_BASE = 30

# ── 실제 DOM 기반 확정 selector (2026-03-11 직접 확인) ──
COMMENT_INPUT_SELECTOR  = "textarea.comment_inbox_text"
COMMENT_SUBMIT_SELECTOR = ".register_box button, .register_box .btn_register"

TITLE_SELECTORS   = [".title-text", "h3.title", ".ArticleTitle", ".article-title"]
CONTENT_SELECTORS = [".se-main-container", ".se-text-paragraph", ".tbody", ".article_body"]
AUTHOR_SELECTORS  = [".writer-nick-wrap .nick", ".cafe-nick-name", ".writer_info .nick"]


# ──────────────────────────────────────────
# 템플릿
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
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.0-flash")
    except Exception:
        return None


def generate_welcome_comment(post_title: str, post_content: str, author: str) -> str:
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
                generation_config=genai.GenerationConfig(temperature=0.8, max_output_tokens=200),
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
                logger.warning(f"[writer] Gemini 429 → {wait_sec}초 대기 ({attempt}/{GEMINI_MAX_RETRY})")
                if attempt < GEMINI_MAX_RETRY:
                    time.sleep(wait_sec)
                    continue
            else:
                logger.error(f"[writer] Gemini 실패: {e}")
            break

    return random.choice(WELCOME_TEMPLATES)


# ──────────────────────────────────────────
# 게시글 내용 읽기
# ──────────────────────────────────────────
async def _read_post_content(page: Page) -> tuple[str, str, str]:
    """iframe 없이 page 직접 사용 (v4.0 확정)"""
    async def try_selectors(selectors: list[str]) -> str:
        for sel in selectors:
            try:
                text = await page.locator(sel).first.text_content(timeout=5000)
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return ""

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        title   = await try_selectors(TITLE_SELECTORS)
        content = await try_selectors(CONTENT_SELECTORS)
        author  = await try_selectors(AUTHOR_SELECTORS) or "알수없음"
        logger.debug(f"[writer] 읽기 완료: '{title[:30]}' / {author}")
        return title, content, author
    except Exception as e:
        logger.error(f"[writer] 내용 읽기 실패: {e}")
        return "", "", "알수없음"


# ──────────────────────────────────────────
# 댓글 입력 및 제출
# ──────────────────────────────────────────
async def _submit_comment(page: Page, comment_text: str) -> bool:
    """
    댓글 작성 및 제출
    v4.0: 실제 DOM 확인 기반 — iframe 없이 page 직접 사용
      입력창: textarea.comment_inbox_text
      제출버튼: .register_box button
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # 1. 입력창 대기
        try:
            await page.wait_for_selector(COMMENT_INPUT_SELECTOR, state="visible", timeout=ACTION_TIMEOUT)
        except Exception:
            logger.error(f"[writer] 입력창 없음: '{COMMENT_INPUT_SELECTOR}'")
            # 디버그: 현재 textarea 목록 출력
            all_ta = await page.locator("textarea").all()
            logger.debug(f"[writer] textarea 개수: {len(all_ta)}")
            for i, ta in enumerate(all_ta[:5]):
                cls = await ta.get_attribute("class") or ""
                ph  = await ta.get_attribute("placeholder") or ""
                logger.debug(f"[writer]   [{i}] class='{cls}' placeholder='{ph}'")
            return False

        input_el = page.locator(COMMENT_INPUT_SELECTOR).first

        if await input_el.is_disabled():
            logger.error("[writer] 입력창 비활성화 — 로그인 상태 확인 필요")
            return False

        # 2. 타이핑
        await input_el.click()
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await input_el.type(comment_text, delay=random.randint(60, 130))
        await asyncio.sleep(random.uniform(0.8, 1.5))

        typed = await input_el.input_value()
        if not typed:
            logger.error("[writer] 입력 후 내용 비어있음")
            return False

        # 3. 제출 버튼
        try:
            await page.wait_for_selector(COMMENT_SUBMIT_SELECTOR, state="visible", timeout=ACTION_TIMEOUT)
        except Exception:
            logger.error(f"[writer] 제출 버튼 없음: '{COMMENT_SUBMIT_SELECTOR}'")
            return False

        await page.locator(COMMENT_SUBMIT_SELECTOR).first.click()
        await asyncio.sleep(2.5)

        # 4. 성공 검증 (입력창 초기화 확인)
        after_value = await input_el.input_value()
        if after_value == "":
            logger.debug("[writer] 제출 성공 확인 (입력창 초기화됨)")
        else:
            logger.warning("[writer] 제출 후 입력창 내용 남아있음 — 실패 가능성")

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
    main.py에서 호출하는 단일 진입점
    """
    success_count = 0
    logger.info(f"[writer] 시작 | 대상: {len(post_urls)}개")

    for idx, url in enumerate(post_urls):
        try:
            if is_post_processed(url):
                logger.debug(f"[writer] 이미 처리됨 ({idx+1}/{len(post_urls)})")
                continue

            logger.info(f"[writer] 처리 ({idx+1}/{len(post_urls)}): {url[-60:]}")

            await page.goto(url, timeout=25000, wait_until="domcontentloaded")
            await asyncio.sleep(PAGE_LOAD_WAIT_S)

            title, content, author = await _read_post_content(page)

            # 관리자/봇 본인 글 스킵
            if any(bn.lower() in author.lower() for bn in BOT_NICKNAMES):
                logger.debug(f"[writer] 관리자 글 스킵: '{author}'")
                mark_post_processed(url, author)
                continue

            comment = await asyncio.get_event_loop().run_in_executor(
                None, generate_welcome_comment, title, content, author
            )

            submitted = await _submit_comment(page, comment)

            if submitted:
                success_count += 1
                mark_post_processed(url, author)
                log_welcome_comment(url, author, comment)
                logger.info(f"[writer] ✅ 완료: {author} — '{title[:30]}'")
            else:
                logger.warning(f"[writer] ❌ 실패: {url[-60:]}")

            await asyncio.sleep(random.uniform(3.0, 6.0))

        except Exception as e:
            logger.error(f"[writer] 오류 [{url[-50:]}]: {e}", exc_info=True)

    logger.info(f"[writer] 완료 | {success_count}/{len(post_urls)}")
    return success_count
