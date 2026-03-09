// ============================================================
// 파일명: Header.tsx
// 경로:   cafe-bot-dashboard/components/layout/Header.tsx
// 역할:   상단 헤더 — 타이틀, 마지막 실행 시각, 새로고침 버튼
// 작성일: 2026-03-10
// ============================================================

"use client";

import { RefreshCw } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { ko } from "date-fns/locale";

interface HeaderProps {
  lastRunAt:    string | null; // 마지막 실행 ISO 시각
  isRefreshing: boolean;
  onRefresh:    () => void;
}

export default function Header({ lastRunAt, isRefreshing, onRefresh }: HeaderProps) {
  // 마지막 실행 시각 포맷 (예: "3분 전")
  const lastRunLabel = lastRunAt
    ? formatDistanceToNow(new Date(lastRunAt), { addSuffix: true, locale: ko })
    : "정보 없음";

  return (
    <header className="sticky top-0 z-10 bg-[#0D1117]/80 backdrop-blur-md border-b border-[#30363D]">
      <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">

        {/* 좌측: 타이틀 */}
        <div className="flex items-center gap-2.5">
          {/* 봇 아이콘 */}
          <div className="w-8 h-8 rounded-lg bg-[#1A4A2A] flex items-center justify-center text-base">
            🤖
          </div>
          <div>
            <h1 className="text-sm font-bold text-[#E6EDF3] leading-tight">
              알렉스강 카페봇
            </h1>
            <p className="text-xs text-[#8B949E] leading-tight">
              마지막 실행: {lastRunLabel}
            </p>
          </div>
        </div>

        {/* 우측: 새로고침 버튼 */}
        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className="
            flex items-center gap-1.5 px-3 py-1.5
            text-xs font-medium text-[#8B949E]
            bg-[#1C2128] border border-[#30363D] rounded-lg
            hover:text-[#E6EDF3] hover:border-[#484F58]
            disabled:opacity-50 disabled:cursor-not-allowed
            transition-all duration-200
          "
          aria-label="데이터 새로고침"
        >
          <RefreshCw
            size={13}
            className={isRefreshing ? "animate-spin" : ""}
          />
          <span className="hidden sm:inline">새로고침</span>
        </button>
      </div>
    </header>
  );
}
