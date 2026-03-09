// ============================================================
// 파일명: supabase.ts
// 경로:   cafe-bot-dashboard/lib/supabase.ts
// 역할:   Supabase 클라이언트 싱글톤 + 데이터 조회 함수 전담
//
// 설계 원칙:
//   - 클라이언트는 싱글톤으로 한 번만 생성 (성능 최적화)
//   - 모든 DB 조회 함수는 이 파일에서만 관리 (단일 책임)
//   - 조회 실패 시 빈 배열/기본값 반환 (UI 크래시 방지)
//
// 작성일: 2026-03-10
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
/**
 * 오늘(KST) bot_run_logs에서 통계 합산
 * 안전장치: 오류 시 모든 값 0 반환
 */
export async function fetchTodayStats(): Promise<TodayStats> {
  const defaultStats: TodayStats = {
    runCount: 0,
    spamDeleted: 0,
    welcomeCommented: 0,
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
      .select("posts_checked, spam_deleted, welcome_commented")
      .gte("run_at", todayKST.toISOString());

    if (error) throw error;
    if (!data || data.length === 0) return defaultStats;

    return data.reduce(
      (acc, row) => ({
        runCount:         acc.runCount + 1,
        spamDeleted:      acc.spamDeleted + (row.spam_deleted ?? 0),
        welcomeCommented: acc.welcomeCommented + (row.welcome_commented ?? 0),
        postsChecked:     acc.postsChecked + (row.posts_checked ?? 0),
      }),
      defaultStats
    );
  } catch (err) {
    console.error("[supabase] fetchTodayStats 오류:", err);
    return defaultStats;
  }
}

// ── 최근 실행 로그 ───────────────────────────────────────────
/**
 * 봇 실행 이력 최근 N건 조회
 */
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
/**
 * 삭제된 스팸 댓글 최근 N건 조회
 */
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
/**
 * 작성된 환영 댓글 최근 N건 조회
 */
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
