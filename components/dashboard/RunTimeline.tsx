// ============================================================
// 파일명: RunTimeline.tsx
// 경로:   naver-cafe-bot/components/dashboard/RunTimeline.tsx
// 역할:   봇 최근 실행 이력 타임라인 (최근 10건)
//
// 작성일: 2026-03-10
// 수정일: 2026-03-10
// 버전:   v1.1
//
// [v1.1 — 2026-03-10]
//   Bug Fix: DB 컬럼명 일치
//     - welcome_commented → welcome_sent
//     - run_duration_sec 제거 (DB에 없음)
// ============================================================

import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { BotRunLog } from "@/lib/types";
import Badge from "@/components/ui/Badge";

interface RunTimelineProps {
  logs:      BotRunLog[];
  isLoading: boolean;
}

function getStatusConfig(status: string) {
  switch (status) {
    case "success":
      return { variant: "success" as const, label: "성공" };
    case "partial_error":
      return { variant: "warning" as const, label: "부분 오류" };
    case "failed":
      return { variant: "error" as const, label: "실패" };
    default:
      return { variant: "neutral" as const, label: "알 수 없음" };
  }
}

export default function RunTimeline({ logs, isLoading }: RunTimelineProps) {
  return (
    <div className="card animate-enter">
      <p className="section-title">최근 실행 이력</p>

      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-10 bg-[#30363D] rounded-lg animate-pulse-soft" />
          ))}
        </div>
      )}

      {!isLoading && logs.length === 0 && (
        <p className="text-sm text-[#484F58] text-center py-6">
          실행 이력이 없습니다.
        </p>
      )}

      {!isLoading && logs.length > 0 && (
        <div className="space-y-2">
          {logs.map((log, idx) => {
            const { variant, label } = getStatusConfig(log.status);
            const runTime = format(new Date(log.run_at), "MM/dd HH:mm", { locale: ko });

            return (
              <div
                key={log.id}
                className="
                  flex items-center justify-between
                  px-3 py-2.5 rounded-lg
                  bg-[#0D1117] border border-[#30363D]
                  hover:border-[#484F58] transition-colors
                "
                style={{ animationDelay: `${idx * 50}ms` }}
              >
                {/* 좌측: 시각 + 상태 */}
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="font-stat text-xs text-[#8B949E] shrink-0">
                    {runTime}
                  </span>
                  <Badge variant={variant}>{label}</Badge>
                  {log.error_message && (
                    <span className="text-xs text-[#F85149] truncate max-w-[120px]" title={log.error_message}>
                      {log.error_message}
                    </span>
                  )}
                </div>

                {/* 우측: 통계 */}
                <div className="flex items-center gap-3 shrink-0 ml-2">
                  <span className="text-xs text-[#8B949E] hidden sm:block">
                    게시글 <span className="text-[#E6EDF3] font-stat">{log.posts_checked}</span>
                  </span>
                  <span className="text-xs text-[#F85149]">
                    스팸 <span className="font-stat">{log.spam_deleted}</span>
                  </span>
                  <span className="text-xs text-[#3FB950]">
                    환영 <span className="font-stat">{log.welcome_sent}</span>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
