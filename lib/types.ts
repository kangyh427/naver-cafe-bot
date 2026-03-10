// ============================================================
// 파일명: types.ts
// 경로:   cafe-bot-dashboard/lib/types.ts
// 역할:   Supabase 테이블 구조와 1:1 매핑되는 TypeScript 타입 정의
//
// 수정일: 2026-03-11 (v1.2)
// [v1.2]
//   근본 수정: DB 실제 컬럼명과 완전 일치
//   bot_run_logs 실제 컬럼 기준:
//     welcome_commented → welcome_sent
//     run_duration_sec  → 제거 (DB에 없는 컬럼)
//   TodayStats:
//     welcomeCommented  → welcomeSent
// ============================================================

// ── bot_run_logs 테이블 — DB 실제 컬럼명과 1:1 매핑 ────────
export interface BotRunLog {
  id:                number;
  posts_checked:     number;
  spam_deleted:      number;
  welcome_sent:      number;   // DB 실제 컬럼명
  error_count:       number;
  // run_duration_sec: DB에 없는 컬럼 — 제거
  status:            "success" | "partial_error" | "failed";
  error_message:     string | null;
  run_at:            string;   // ISO 8601
}

// ── spam_logs 테이블 ────────────────────────────────────────
export interface SpamLog {
  id:               number;
  post_url:         string;
  comment_author:   string;
  comment_content:  string | null;
  spam_reason:      string | null;
  ai_confidence:    number | null;
  keyword_matched:  string | null;
  deleted_at:       string;
}

// ── welcome_logs 테이블 ─────────────────────────────────────
export interface WelcomeLog {
  id:              number;
  post_url:        string;
  post_author:     string;
  comment_content: string | null;
  commented_at:    string;
}

// ── processed_posts 테이블 ──────────────────────────────────
export interface ProcessedPost {
  id:           number;
  post_url:     string;
  post_author:  string | null;
  processed_at: string;
}

// ── 대시보드 UI 전용 타입 ────────────────────────────────────
export interface TodayStats {
  runCount:    number;
  spamDeleted: number;
  welcomeSent: number;   // welcomeCommented → welcomeSent
  postsChecked: number;
}

export type BotStatus = "active" | "idle" | "error" | "unknown";

export interface TriggerResponse {
  success: boolean;
  message: string;
}
