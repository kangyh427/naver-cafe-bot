// ============================================================
// 파일명: StatCards.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/StatCards.tsx
// 역할:   오늘 통계 4개 카드 (실행 횟수, 스팸 삭제, 환영 댓글, 게시글)
// 작성일: 2026-03-10
// ============================================================

import { TodayStats } from "@/lib/types";

interface StatCardsProps {
  stats:     TodayStats;
  isLoading: boolean;
}

interface CardConfig {
  label:    string;
  value:    number;
  icon:     string;
  color:    string; // 숫자 강조 색상
  bgColor:  string; // 아이콘 배경
}

export default function StatCards({ stats, isLoading }: StatCardsProps) {
  const cards: CardConfig[] = [
    {
      label:   "오늘 실행",
      value:   stats.runCount,
      icon:    "⚡",
      color:   "text-[#58A6FF]",
      bgColor: "bg-[#0A1F3D]",
    },
    {
      label:   "스팸 삭제",
      value:   stats.spamDeleted,
      icon:    "🗑️",
      color:   "text-[#F85149]",
      bgColor: "bg-[#3D0A0A]",
    },
    {
      label:   "환영 댓글",
      value:   stats.welcomeCommented,
      icon:    "💬",
      color:   "text-[#3FB950]",
      bgColor: "bg-[#1A4A2A]",
    },
    {
      label:   "게시글 확인",
      value:   stats.postsChecked,
      icon:    "📋",
      color:   "text-[#D29922]",
      bgColor: "bg-[#3D2E0A]",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="card animate-enter flex flex-col gap-3"
        >
          {/* 아이콘 */}
          <div
            className={`w-9 h-9 rounded-lg ${card.bgColor} flex items-center justify-center text-lg`}
          >
            {card.icon}
          </div>

          {/* 숫자 */}
          <div>
            {isLoading ? (
              <div className="h-7 w-12 bg-[#30363D] rounded animate-pulse-soft" />
            ) : (
              <p className={`text-2xl font-bold font-stat ${card.color}`}>
                {card.value.toLocaleString()}
              </p>
            )}
            <p className="text-xs text-[#8B949E] mt-0.5">{card.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
