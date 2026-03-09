// ============================================================
// 파일명: types.ts
// 경로:   cafe-bot-dashboard/lib/types.ts
// 역할:   Supabase 테이블 구조와 1:1 매핑되는 TypeScript 타입 정의
//         모든 컴포넌트에서 이 타입을 import하여 사용
// 작성일: 2026-03-10
// ============================================================

// ── Supabase 테이블 타입 ─────────────────────────────────────

/** bot_run_logs 테이블 — 봇 1회 실행 이력 */
export interface BotRunLog {
  id:                number;
  posts_checked:     number;
  spam_deleted:      number;
  welcome_commented: number;
  error_count:       number;
  run_duration_sec:  number | null;
  status:            "success" | "partial_error" | "failed";
  error_message:     string | null;
  run_at:            string; // ISO 8601
}

/** spam_logs 테이블 — 삭제된 스팸 댓글 */
export interface SpamLog {
  id:               number;
  post_url:         string;
  comment_author:   string;
  comment_content:  string | null;
  spam_reason:      string | null;
  ai_confidence:    number | null;
  keyword_matched:  string | null;
  deleted_at:       string; // ISO 8601
}

/** welcome_logs 테이블 — 작성된 환영 댓글 */
export interface WelcomeLog {
  id:              number;
  post_url:        string;
  post_author:     string;
  comment_content: string | null;
  commented_at:    string; // ISO 8601
}

/** processed_posts 테이블 — 처리 완료 게시글 */
export interface ProcessedPost {
  id:           number;
  post_url:     string;
  post_author:  string | null;
  processed_at: string; // ISO 8601
}

// ── 대시보드 UI 전용 타입 ────────────────────────────────────

/** 오늘 통계 카드에 표시할 집계 데이터 */
export interface TodayStats {
  runCount:         number; // 오늘 실행 횟수
  spamDeleted:      number; // 오늘 삭제한 스팸 수
  welcomeCommented: number; // 오늘 작성한 환영 댓글 수
  postsChecked:     number; // 오늘 확인한 게시글 수
}

/** 봇 상태 */
export type BotStatus = "active" | "idle" | "error" | "unknown";

/** GitHub Actions API 트리거 응답 */
export interface TriggerResponse {
  success: boolean;
  message: string;
}
