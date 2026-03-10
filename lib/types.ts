// ============================================================
// 파일명: types.ts
// 경로:   naver-cafe-bot/lib/types.ts
// 역할:   Supabase 테이블 구조와 1:1 매핑되는 TypeScript 타입 정의
//
// 작성일: 2026-03-10
// 수정일: 2026-03-10
// 버전:   v1.1
//
// [v1.1 — 2026-03-10]
//   Bug Fix: DB 실제 컬럼명과 불일치 수정
//     - welcome_commented → welcome_sent
//     - error_count, run_duration_sec 제거 (DB에 없음)
//     - comments_checked 추가
//
// [v1.0 — 2026-03-10]
//   최초 작성
// ============================================================

// ── Supabase 테이블 타입 ─────────────────────────────────────

/** bot_run_logs 테이블 — 봇 1회 실행 이력 */
export interface BotRunLog {
  id:                string;       // uuid
  run_at:            string;       // timestamptz (ISO 8601)
  status:            string;       // varchar
  posts_checked:     number;       // int4
  comments_checked:  number;       // int4
  spam_deleted:      number;       // int4
  welcome_sent:      number;       // int4
  error_message:     string | null; // text
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
  id:           string;        // uuid
  post_url:     string;
  post_type:    string | null; // varchar
  processed_at: string;        // timestamptz
}

// ── 대시보드 UI 전용 타입 ────────────────────────────────────

/** 오늘 통계 카드에 표시할 집계 데이터 */
export interface TodayStats {
  runCount:         number; // 오늘 실행 횟수
  spamDeleted:      number; // 오늘 삭제한 스팸 수
  welcomeSent:      number; // 오늘 작성한 환영 댓글 수
  postsChecked:     number; // 오늘 확인한 게시글 수
}

/** 봇 상태 */
export type BotStatus = "active" | "idle" | "error" | "unknown";

/** GitHub Actions API 트리거 응답 */
export interface TriggerResponse {
  success: boolean;
  message: string;
}
