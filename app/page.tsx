// ============================================================
// 파일명: page.tsx
// 경로:   cafe-bot-dashboard/app/page.tsx
//
// 수정일: 2026-03-11 (v1.2)
// [v1.2] welcomeCommented → welcomeSent / 자동갱신 제거 / 누적 이력
// ============================================================

"use client";

import { useState, useEffect, useCallback } from "react";
import Header      from "@/components/layout/Header";
import StatCards   from "@/components/dashboard/StatCards";
import BotToggle   from "@/components/dashboard/BotToggle";
import RunTimeline from "@/components/dashboard/RunTimeline";
import SpamList    from "@/components/dashboard/SpamList";
import WelcomeList from "@/components/dashboard/WelcomeList";
import { fetchTodayStats, fetchRecentRunLogs, fetchRecentSpamLogs, fetchRecentWelcomeLogs } from "@/lib/supabase";
import type { TodayStats, BotRunLog, SpamLog, WelcomeLog } from "@/lib/types";

const DEFAULT_STATS: TodayStats = { runCount: 0, spamDeleted: 0, welcomeSent: 0, postsChecked: 0 };
const PAGE_SIZE_RUNS = 20;
const PAGE_SIZE_LOGS = 30;
const INITIAL_FETCH  = 100;

export default function DashboardPage() {
  const [stats,       setStats]       = useState<TodayStats>(DEFAULT_STATS);
  const [runLogs,     setRunLogs]     = useState<BotRunLog[]>([]);
  const [spamLogs,    setSpamLogs]    = useState<SpamLog[]>([]);
  const [welcomeLogs, setWelcomeLogs] = useState<WelcomeLog[]>([]);
  const [isLoading,   setIsLoading]   = useState(true);
  const [runPage,     setRunPage]     = useState(1);
  const [spamPage,    setSpamPage]    = useState(1);
  const [welcomePage, setWelcomePage] = useState(1);

  const loadAll = useCallback(async () => {
    setIsLoading(true);
    setRunPage(1); setSpamPage(1); setWelcomePage(1);
    try {
      const [todayStats, runs, spams, welcomes] = await Promise.all([
        fetchTodayStats(),
        fetchRecentRunLogs(INITIAL_FETCH),
        fetchRecentSpamLogs(INITIAL_FETCH),
        fetchRecentWelcomeLogs(INITIAL_FETCH),
      ]);
      setStats(todayStats);
      setRunLogs(runs);
      setSpamLogs(spams);
      setWelcomeLogs(welcomes);
    } catch (err) {
      console.error("[page] 데이터 로드 오류:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // 첫 접속 시 1회만 로드 (자동 갱신 없음)
  useEffect(() => { loadAll(); }, [loadAll]);

  const pagedRunLogs     = runLogs.slice(0, runPage * PAGE_SIZE_RUNS);
  const pagedSpamLogs    = spamLogs.slice(0, spamPage * PAGE_SIZE_LOGS);
  const pagedWelcomeLogs = welcomeLogs.slice(0, welcomePage * PAGE_SIZE_LOGS);
  const lastRun          = runLogs[0] ?? null;

  return (
    <div className="min-h-screen bg-[#0D1117]">
      <Header lastRunAt={lastRun?.run_at ?? null} isRefreshing={isLoading} onRefresh={loadAll} />
      <main className="max-w-5xl mx-auto px-4 py-5 space-y-4">
        <StatCards stats={stats} isLoading={isLoading} />
        <BotToggle lastRun={lastRun} onTriggered={loadAll} />
        <RunTimeline
          logs={pagedRunLogs} totalCount={runLogs.length}
          isLoading={isLoading} hasMore={pagedRunLogs.length < runLogs.length}
          onLoadMore={() => setRunPage(p => p + 1)}
        />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SpamList
            logs={pagedSpamLogs} totalCount={spamLogs.length}
            isLoading={isLoading} hasMore={pagedSpamLogs.length < spamLogs.length}
            onLoadMore={() => setSpamPage(p => p + 1)}
          />
          <WelcomeList
            logs={pagedWelcomeLogs} totalCount={welcomeLogs.length}
            isLoading={isLoading} hasMore={pagedWelcomeLogs.length < welcomeLogs.length}
            onLoadMore={() => setWelcomePage(p => p + 1)}
          />
        </div>
        <p className="text-center text-xs text-[#484F58] pb-4">
          알렉스강의 주식이야기 카페봇 대시보드
        </p>
      </main>
    </div>
  );
}
