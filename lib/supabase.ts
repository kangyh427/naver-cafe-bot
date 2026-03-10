// ============================================================
// 파일명: supabase.ts
// 경로:   naver-cafe-bot/lib/supabase.ts
// 역할:   Supabase 클라이언트 싱글톤 + 데이터 조회 함수 전담
//
// 작성일: 2026-03-10
// 수정일: 2026-03-10
// 버전:   v1.1
//
// [v1.1 — 2026-03-10]
//   Bug Fix: DB 실제 컬럼명과 불일치 수정
//     - welcome_commented → welcome_sent
//     - run_duration_sec 제거
//     - comments_checked 반영
//
// [v1.0 — 2026-03-10]
//   최초 작성
// ============================================================

import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { BotRunLog, SpamLog, TodayStats, WelcomeLog } from "./types";

// ── 클라이언트 싱글톤 ────────────────────────────────────────
let _client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !key) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL 또는 NEXT_PUBLIC_SUPABASE_ANON_KEY 환경변수가 누락되었습니다."
    );
  }

  _client = createClient(url, key);
  return _client;
}

// ── 오늘 통계 집계 ───────────────────────────────────────────
export async function fetchTodayStats(): Promise<TodayStats> {
  const defaultStats: TodayStats = {
    runCount: 0,
    spamDeleted: 0,
    welcomeSent: 0,
    postsChecked: 0,
  };

  try {
    const supabase = getSupabaseClient();

    // 오늘 KST 00:00 기준 UTC 변환
    const now = new Date();
    const kstOffset = 9 * 60 * 60 * 1000;
    const todayKST = new Date(
      Math.floor((now.getTime() + kstOffset) / 86400000) * 86400000 - kstOffset
    );

    const { data, error } = await supabase
      .from("bot_run_logs")
      .select("posts_checked, spam_deleted, welcome_sent")
      .gte("run_at", todayKST.toISOString());

    if (error) throw error;
    if (!data || data.length === 0) return defaultStats;

    return data.reduce(
      (acc, row) => ({
        runCount:     acc.runCount + 1,
        spamDeleted:  acc.spamDeleted + (row.spam_deleted ?? 0),
        welcomeSent:  acc.welcomeSent + (row.welcome_sent ?? 0),
        postsChecked: acc.postsChecked + (row.posts_checked ?? 0),
      }),
      defaultStats
    );
  } catch (err) {
    console.error("[supabase] fetchTodayStats 오류:", err);
    return defaultStats;
  }
}

// ── 최근 실행 로그 ───────────────────────────────────────────
export async function fetchRecentRunLogs(limit = 10): Promise<BotRunLog[]> {
  try {
    const supabase = getSupabaseClient();
    const { data, error } = await supabase
      .from("bot_run_logs")
      .select("*")
      .order("run_at", { ascending: false })
      .limit(limit);

    if (error) throw error;
    return data ?? [];
  } catch (err) {
    console.error("[supabase] fetchRecentRunLogs 오류:", err);
    return [];
  }
}

// ── 스팸 목록 ────────────────────────────────────────────────
export async function fetchRecentSpamLogs(limit = 20): Promise<SpamLog[]> {
  try {
    const supabase = getSupabaseClient();
    const { data, error } = await supabase
      .from("spam_logs")
      .select("*")
      .order("deleted_at", { ascending: false })
      .limit(limit);

    if (error) throw error;
    return data ?? [];
  } catch (err) {
    console.error("[supabase] fetchRecentSpamLogs 오류:", err);
    return [];
  }
}

// ── 환영 댓글 목록 ───────────────────────────────────────────
export async function fetchRecentWelcomeLogs(limit = 20): Promise<WelcomeLog[]> {
  try {
    const supabase = getSupabaseClient();
    const { data, error } = await supabase
      .from("welcome_logs")
      .select("*")
      .order("commented_at", { ascending: false })
      .limit(limit);

    if (error) throw error;
    return data ?? [];
  } catch (err) {
    console.error("[supabase] fetchRecentWelcomeLogs 오류:", err);
    return [];
  }
}
