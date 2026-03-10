// ============================================================
// 파일명: page.tsx
// 경로:   naver-cafe-bot/app/page.tsx
// 역할:   대시보드 메인 페이지 — 데이터 조회 + 컴포넌트 조합
//
// 작성일: 2026-03-10
// 수정일: 2026-03-10
// 버전:   v1.1
//
// [v1.1 — 2026-03-10]
//   Bug Fix: TodayStats 필드명 수정 (welcomeCommented → welcomeSent)
// ============================================================

"use client";

import { useState, useEffect, useCallback } from "react";
import Header from "@/components/layout/Header";
import StatCards from "@/components/dashboard/StatCards";
import BotToggle from "@/components/dashboard/BotToggle";
import RunTimeline from "@/components/dashboard/RunTimeline";
import SpamList from "@/components/dashboard/SpamList";
import WelcomeList from "@/components/dashboard/WelcomeList";

import {
  fetchTodayStats,
  fetchRecentRunLogs,
  fetchRecentSpamLogs,
  fetchRecentWelcomeLogs,
} from "@/lib/supabase";
import type { TodayStats, BotRunLog, SpamLog, WelcomeLog } from "@/lib/types";

// ── 초기 빈 상태 ────────────────────────────────────────────
const DEFAULT_STATS: TodayStats = {
  runCount: 0, spamDeleted: 0, welcomeSent: 0, postsChecked: 0,
};

// ── 자동 새로고침 주기 (밀리초) ─────────────────────────────
const AUTO_REFRESH_MS = 60_000;

export default function DashboardPage() {
  const [stats,       setStats]       = useState<TodayStats>(DEFAULT_STATS);
  const [runLogs,     setRunLogs]     = useState<BotRunLog[]>([]);
  const [spamLogs,    setSpamLogs]    = useState<SpamLog[]>([]);
  const [welcomeLogs, setWelcomeLogs] = useState<WelcomeLog[]>([]);
  const [isLoading,   setIsLoading]   = useState(true);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setIsLoading(true);
    try {
      const [todayStats, runs, spams, welcomes] = await Promise.all([
        fetchTodayStats(),
        fetchRecentRunLogs(10),
        fetchRecentSpamLogs(20),
        fetchRecentWelcomeLogs(20),
      ]);
      setStats(todayStats);
      setRunLogs(runs);
      setSpamLogs(spams);
      setWelcomeLogs(welcomes);
      setLastRefresh(new Date().toISOString());
    } catch (err) {
      console.error("[page] 데이터 로드 오류:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    const timer = setInterval(loadAll, AUTO_REFRESH_MS);
    return () => clearInterval(timer);
  }, [loadAll]);

  const lastRun = runLogs[0] ?? null;

  return (
    <div className="min-h-screen bg-[#0D1117]">
      <Header
        lastRunAt={lastRun?.run_at ?? null}
        isRefreshing={isLoading}
        onRefresh={loadAll}
      />

      <main className="max-w-5xl mx-auto px-4 py-5 space-y-4">
        <StatCards stats={stats} isLoading={isLoading} />
        <BotToggle lastRun={lastRun} onTriggered={loadAll} />
        <RunTimeline logs={runLogs} isLoading={isLoading} />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SpamList    logs={spamLogs}    isLoading={isLoading} />
          <WelcomeList logs={welcomeLogs} isLoading={isLoading} />
        </div>

        <p className="text-center text-xs text-[#484F58] pb-4">
          알렉스강의 주식이야기 카페봇 · 60초마다 자동 갱신
          {lastRefresh && (
            <span className="ml-2 font-stat">
              {new Date(lastRefresh).toLocaleTimeString("ko-KR")} 기준
            </span>
          )}
        </p>
      </main>
    </div>
  );
}
