// ============================================================
// 파일명: page.tsx
// 경로:   cafe-bot-dashboard/app/page.tsx
// 역할:   대시보드 메인 페이지
//
// 수정일: 2026-03-11 (v1.2)
// [v1.2]
//   - 60초 자동 갱신 제거 → 수동 새로고침 + 첫 접속 시 1회만 로드
//   - 실행 이력: 최근 10건 → 전체 누적 (페이지네이션)
//   - 스팸/환영 댓글: 최근 20건 → 전체 누적 (페이지네이션)
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

// ── 초기 빈 상태 ─────────────────────────────────────────────
const DEFAULT_STATS: TodayStats = {
  runCount: 0, spamDeleted: 0, welcomeCommented: 0, postsChecked: 0,
};

// ── 페이지당 표시 건수 ────────────────────────────────────────
const PAGE_SIZE_RUNS    = 20;  // 실행 이력 페이지당 건수
const PAGE_SIZE_LOGS    = 30;  // 스팸/환영 댓글 페이지당 건수
const INITIAL_FETCH     = 100; // 초기 로드 건수 (충분히 크게)

export default function DashboardPage() {
  // ── 상태 관리 ──────────────────────────────────────────────
  const [stats,       setStats]       = useState<TodayStats>(DEFAULT_STATS);
  const [runLogs,     setRunLogs]     = useState<BotRunLog[]>([]);
  const [spamLogs,    setSpamLogs]    = useState<SpamLog[]>([]);
  const [welcomeLogs, setWelcomeLogs] = useState<WelcomeLog[]>([]);
  const [isLoading,   setIsLoading]   = useState(true);

  // ── 페이지 상태 (각 섹션 독립) ───────────────────────────
  const [runPage,     setRunPage]     = useState(1);
  const [spamPage,    setSpamPage]    = useState(1);
  const [welcomePage, setWelcomePage] = useState(1);

  // ── 전체 데이터 로드 (첫 접속 + 수동 새로고침만) ─────────
  const loadAll = useCallback(async () => {
    setIsLoading(true);
    // 페이지 초기화
    setRunPage(1);
    setSpamPage(1);
    setWelcomePage(1);
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

  // ── 첫 접속 시 1회만 로드 (자동 갱신 없음) ───────────────
  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // ── 페이지네이션 계산 ─────────────────────────────────────
  const pagedRunLogs     = runLogs.slice(0, runPage * PAGE_SIZE_RUNS);
  const pagedSpamLogs    = spamLogs.slice(0, spamPage * PAGE_SIZE_LOGS);
  const pagedWelcomeLogs = welcomeLogs.slice(0, welcomePage * PAGE_SIZE_LOGS);

  const lastRun = runLogs[0] ?? null;

  return (
    <div className="min-h-screen bg-[#0D1117]">
      {/* 헤더 — 수동 새로고침 버튼 포함 */}
      <Header
        lastRunAt={lastRun?.run_at ?? null}
        isRefreshing={isLoading}
        onRefresh={loadAll}
      />

      <main className="max-w-5xl mx-auto px-4 py-5 space-y-4">

        {/* 오늘 통계 카드 */}
        <StatCards stats={stats} isLoading={isLoading} />

        {/* 봇 제어 */}
        <BotToggle lastRun={lastRun} onTriggered={loadAll} />

        {/* 실행 이력 타임라인 — 전체 누적 */}
        <RunTimeline
          logs={pagedRunLogs}
          totalCount={runLogs.length}
          isLoading={isLoading}
          hasMore={pagedRunLogs.length < runLogs.length}
          onLoadMore={() => setRunPage(p => p + 1)}
        />

        {/* 스팸 삭제 + 환영 댓글 — 전체 누적 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SpamList
            logs={pagedSpamLogs}
            totalCount={spamLogs.length}
            isLoading={isLoading}
            hasMore={pagedSpamLogs.length < spamLogs.length}
            onLoadMore={() => setSpamPage(p => p + 1)}
          />
          <WelcomeList
            logs={pagedWelcomeLogs}
            totalCount={welcomeLogs.length}
            isLoading={isLoading}
            hasMore={pagedWelcomeLogs.length < welcomeLogs.length}
            onLoadMore={() => setWelcomePage(p => p + 1)}
          />
        </div>

        {/* 푸터 — 자동갱신 문구 제거 */}
        <p className="text-center text-xs text-[#484F58] pb-4">
          알렉스강의 주식이야기 카페봇 대시보드
        </p>
      </main>
    </div>
  );
}
