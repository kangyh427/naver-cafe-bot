// ============================================================
// 파일명: supabase.ts
// 경로:   cafe-bot-dashboard/lib/supabase.ts
//
// 수정일: 2026-03-11 (v1.2)
// [v1.2] welcomeCommented → welcomeSent (types.ts 동기화)
// ============================================================

import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { BotRunLog, SpamLog, TodayStats, WelcomeLog } from "./types";

let _client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) throw new Error("Supabase 환경변수 누락");
  _client = createClient(url, key);
  return _client;
}

export async function fetchTodayStats(): Promise<TodayStats> {
  const defaultStats: TodayStats = { runCount: 0, spamDeleted: 0, welcomeSent: 0, postsChecked: 0 };
  try {
    const supabase = getSupabaseClient();
    const kstOffset = 9 * 60 * 60 * 1000;
    const todayKST  = new Date(Math.floor((Date.now() + kstOffset) / 86400000) * 86400000 - kstOffset);
    const { data, error } = await supabase
      .from("bot_run_logs")
      .select("posts_checked, spam_deleted, welcome_sent")
      .gte("run_at", todayKST.toISOString());
    if (error) throw error;
    if (!data || data.length === 0) return defaultStats;
    return data.reduce((acc, row) => ({
      runCount:    acc.runCount + 1,
      spamDeleted: acc.spamDeleted + (row.spam_deleted ?? 0),
      welcomeSent: acc.welcomeSent + (row.welcome_sent  ?? 0),
      postsChecked:acc.postsChecked + (row.posts_checked ?? 0),
    }), defaultStats);
  } catch (err) {
    console.error("[supabase] fetchTodayStats 오류:", err);
    return defaultStats;
  }
}

export async function fetchRecentRunLogs(limit = 100): Promise<BotRunLog[]> {
  try {
    const { data, error } = await getSupabaseClient()
      .from("bot_run_logs").select("*").order("run_at", { ascending: false }).limit(limit);
    if (error) throw error;
    return data ?? [];
  } catch (err) {
    console.error("[supabase] fetchRecentRunLogs 오류:", err);
    return [];
  }
}

export async function fetchRecentSpamLogs(limit = 100): Promise<SpamLog[]> {
  try {
    const { data, error } = await getSupabaseClient()
      .from("spam_logs").select("*").order("deleted_at", { ascending: false }).limit(limit);
    if (error) throw error;
    return data ?? [];
  } catch (err) {
    console.error("[supabase] fetchRecentSpamLogs 오류:", err);
    return [];
  }
}

export async function fetchRecentWelcomeLogs(limit = 100): Promise<WelcomeLog[]> {
  try {
    const { data, error } = await getSupabaseClient()
      .from("welcome_logs").select("*").order("commented_at", { ascending: false }).limit(limit);
    if (error) throw error;
    return data ?? [];
  } catch (err) {
    console.error("[supabase] fetchRecentWelcomeLogs 오류:", err);
    return [];
  }
}
