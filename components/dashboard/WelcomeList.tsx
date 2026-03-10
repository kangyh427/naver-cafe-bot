// ============================================================
// 파일명: WelcomeList.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/WelcomeList.tsx
//
// 수정일: 2026-03-11 (v1.3)
// [v1.3] 더보기 방식 → 페이지 번호 방식 (10건/페이지)
// ============================================================

import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { ExternalLink } from "lucide-react";
import { WelcomeLog } from "@/lib/types";
import Pagination from "@/components/ui/Pagination";

interface WelcomeListProps {
  logs:         WelcomeLog[];
  isLoading:    boolean;
  currentPage:  number;
  totalPages:   number;
  onPageChange: (page: number) => void;
}

export default function WelcomeList({
  logs, isLoading, currentPage, totalPages, onPageChange
}: WelcomeListProps) {
  return (
    <div className="card animate-enter">
      <div className="flex items-center justify-between mb-4">
        <p className="section-title mb-0">환영 댓글 목록</p>
        <span className="font-stat text-xs text-[#8B949E]">
          {totalPages > 0 ? `${currentPage} / ${totalPages} 페이지` : "0건"}
        </span>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-[#30363D] rounded-lg animate-pulse-soft" />
          ))}
        </div>
      )}

      {!isLoading && logs.length === 0 && (
        <p className="text-sm text-[#484F58] text-center py-6">
          작성된 환영 댓글이 없습니다.
        </p>
      )}

      {!isLoading && logs.length > 0 && (
        <>
          <div className="space-y-2">
            {logs.map((log) => {
              const commentedAt = format(new Date(log.commented_at), "MM/dd HH:mm", { locale: ko });

              return (
                <div
                  key={log.id}
                  className="px-3 py-2.5 rounded-lg bg-[#0D1117] border border-[#1A4A2A] hover:border-[#3FB950]/40 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-semibold text-[#3FB950]">
                      {log.post_author}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="font-stat text-xs text-[#484F58]">{commentedAt}</span>
                      <a href={log.post_url} target="_blank" rel="noopener noreferrer"
                        className="text-[#484F58] hover:text-[#58A6FF] transition-colors">
                        <ExternalLink size={12} />
                      </a>
                    </div>
                  </div>
                  {log.comment_content && (
                    <p className="text-xs text-[#8B949E] line-clamp-2 leading-relaxed">
                      {log.comment_content}
                    </p>
                  )}
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
