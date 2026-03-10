// ============================================================
// 파일명: RunTimeline.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/RunTimeline.tsx
//
// 수정일: 2026-03-11 (v1.4)
// [v1.4] 더보기 방식 → 페이지 번호 방식 (10건/페이지)
//        버그수정: interface 중복 선언 제거
// ============================================================

import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { BotRunLog } from "@/lib/types";
import Badge from "@/components/ui/Badge";
import Pagination from "@/components/ui/Pagination";

interface RunTimelineProps {
  logs:         BotRunLog[];
  isLoading:    boolean;
  currentPage:  number;
  totalPages:   number;
  onPageChange: (page: number) => void;
}

function getStatusConfig(status: BotRunLog["status"]) {
  switch (status) {
    case "success":       return { variant: "success" as const, label: "성공" };
    case "partial_error": return { variant: "warning" as const, label: "부분 오류" };
    case "failed":        return { variant: "error"   as const, label: "실패" };
    default:              return { variant: "neutral" as const, label: "알 수 없음" };
  }
}

export default function RunTimeline({
  logs, isLoading, currentPage, totalPages, onPageChange
}: RunTimelineProps) {
  return (
    <div className="card animate-enter">
      <div className="flex items-center justify-between mb-4">
        <p className="section-title mb-0">실행 이력</p>
        <span className="font-stat text-xs text-[#8B949E]">
          {totalPages > 0 ? `${currentPage} / ${totalPages} 페이지` : "0건"}
        </span>
      </div>

      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-10 bg-[#30363D] rounded-lg animate-pulse-soft" />
          ))}
        </div>
      )}

      {!isLoading && logs.length === 0 && (
        <p className="text-sm text-[#484F58] text-center py-6">실행 이력이 없습니다.</p>
      )}

      {!isLoading && logs.length > 0 && (
        <>
          <div className="space-y-2">
            {logs.map((log, idx) => {
              const { variant, label } = getStatusConfig(log.status);
              const runTime = format(new Date(log.run_at), "MM/dd HH:mm", { locale: ko });
              return (
                <div
                  key={log.id}
                  className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-[#0D1117] border border-[#30363D] hover:border-[#484F58] transition-colors"
                  style={{ animationDelay: `${idx * 30}ms` }}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="font-stat text-xs text-[#8B949E] shrink-0">{runTime}</span>
                    <Badge variant={variant}>{label}</Badge>
                    {log.error_message && (
                      <span className="text-xs text-[#F85149] truncate max-w-[120px]" title={log.error_message}>
                        {log.error_message}
                      </span>
                    )}
                  </div>
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

          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={onPageChange}
          />
        </>
      )}
    </div>
  );
}
