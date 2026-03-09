-- ============================================================
-- 파일명: supabase_setup.sql
-- 경로:   kangyh427/naver_cafe_bot/supabase_setup.sql
-- 역할:   Supabase DB 테이블 초기 생성
--
-- 실행 방법:
--   supabase.com → naver-cafe-bot 프로젝트
--   → SQL Editor → New query → 전체 붙여넣기 → Run
--
-- 생성 테이블:
--   spam_logs       — 삭제된 스팸 댓글 기록
--   welcome_logs    — 작성된 환영 댓글 기록
--   processed_posts — 처리 완료 게시글 URL (중복 방지)
--   bot_run_logs    — 봇 실행 이력 및 통계
-- ============================================================

-- ──────────────────────────────────────────
-- 1. 스팸 로그 테이블
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spam_logs (
    id               BIGSERIAL PRIMARY KEY,
    post_url         TEXT        NOT NULL,
    comment_author   TEXT        NOT NULL,
    comment_content  TEXT,
    spam_reason      TEXT,
    ai_confidence    FLOAT,
    keyword_matched  TEXT,
    deleted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  spam_logs IS '삭제된 스팸 댓글 기록';
COMMENT ON COLUMN spam_logs.ai_confidence IS 'Gemini AI 스팸 확신도 (0.0~1.0)';
COMMENT ON COLUMN spam_logs.keyword_matched IS '1차 키워드 필터에서 매칭된 키워드';

-- ──────────────────────────────────────────
-- 2. 환영 댓글 로그 테이블
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS welcome_logs (
    id               BIGSERIAL PRIMARY KEY,
    post_url         TEXT        NOT NULL,
    post_author      TEXT        NOT NULL,
    comment_content  TEXT,
    commented_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE welcome_logs IS '작성된 환영 댓글 기록';

-- ──────────────────────────────────────────
-- 3. 처리된 게시글 URL (중복 환영 댓글 방지)
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS processed_posts (
    id            BIGSERIAL PRIMARY KEY,
    post_url      TEXT        NOT NULL UNIQUE,  -- 중복 방지 UNIQUE
    post_author   TEXT,
    processed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  processed_posts IS '환영 댓글 작성 완료된 게시글 URL 목록';
COMMENT ON COLUMN processed_posts.post_url IS 'UNIQUE — 중복 환영 댓글 원천 차단';

-- URL 조회 성능 향상 인덱스
CREATE INDEX IF NOT EXISTS idx_processed_posts_url ON processed_posts(post_url);

-- ──────────────────────────────────────────
-- 4. 봇 실행 이력 테이블
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_run_logs (
    id                BIGSERIAL PRIMARY KEY,
    posts_checked     INT         NOT NULL DEFAULT 0,
    spam_deleted      INT         NOT NULL DEFAULT 0,
    welcome_commented INT         NOT NULL DEFAULT 0,
    error_count       INT         NOT NULL DEFAULT 0,
    run_duration_sec  FLOAT,
    status            TEXT        NOT NULL DEFAULT 'success',  -- success | partial_error | failed
    error_message     TEXT,
    run_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  bot_run_logs IS '봇 실행 이력 및 통계';
COMMENT ON COLUMN bot_run_logs.status IS 'success | partial_error | failed';

-- ──────────────────────────────────────────
-- 완료 확인 쿼리 (실행 후 아래로 검증)
-- ──────────────────────────────────────────
SELECT
    table_name,
    pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) AS size
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('spam_logs', 'welcome_logs', 'processed_posts', 'bot_run_logs')
ORDER BY table_name;
