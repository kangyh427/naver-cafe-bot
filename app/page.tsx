// ============================================================
// 파일명: page.tsx
// 경로:   cafe-bot-dashboard/app/page.tsx
//
// 수정일: 2026-03-11 (v1.3)
// [v1.3] 더보기 방식 → 페이지 번호 방식 (섹션별 10건/페이지)
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
const PAGE_SIZE     = 10;
const INITIAL_FETCH = 500;

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

  useEffect(() => { loadAll(); }, [loadAll]);

  // 전체 페이지 수 계산
  const runTotalPages     = Math.max(1, Math.ceil(runLogs.length / PAGE_SIZE));
  const spamTotalPages    = Math.max(1, Math.ceil(spamLogs.length / PAGE_SIZE));
  const welcomeTotalPages = Math.max(1, Math.ceil(welcomeLogs.length / PAGE_SIZE));

  // 현재 페이지 데이터 슬라이스
  const pagedRunLogs     = runLogs.slice((runPage - 1) * PAGE_SIZE, runPage * PAGE_SIZE);
  const pagedSpamLogs    = spamLogs.slice((spamPage - 1) * PAGE_SIZE, spamPage * PAGE_SIZE);
  const pagedWelcomeLogs = welcomeLogs.slice((welcomePage - 1) * PAGE_SIZE, welcomePage * PAGE_SIZE);

  const lastRun = runLogs[0] ?? null;

  return (
    <div className="min-h-screen bg-[#0D1117]">
      <Header lastRunAt={lastRun?.run_at ?? null} isRefreshing={isLoading} onRefresh={loadAll} />
      <main className="max-w-5xl mx-auto px-4 py-5 space-y-4">
        <StatCards stats={stats} isLoading={isLoading} />
        <BotToggle lastRun={lastRun} onTriggered={loadAll} />
        <RunTimeline
          logs={pagedRunLogs}
          isLoading={isLoading}
          currentPage={runPage}
          totalPages={runTotalPages}
          onPageChange={setRunPage}
        />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SpamList
            logs={pagedSpamLogs}
            isLoading={isLoading}
            currentPage={spamPage}
            totalPages={spamTotalPages}
            onPageChange={setSpamPage}
          />
          <WelcomeList
            logs={pagedWelcomeLogs}
            isLoading={isLoading}
            currentPage={welcomePage}
            totalPages={welcomeTotalPages}
            onPageChange={setWelcomePage}
          />
        </div>
        <p className="text-center text-xs text-[#484F58] pb-4">
          알렉스강의 주식이야기 카페봇 대시보드
        </p>
      </main>
    </div>
  );
}
