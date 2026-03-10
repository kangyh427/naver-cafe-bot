// ============================================================
// 파일명: SpamList.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/SpamList.tsx
//
// 수정일: 2026-03-11 (v1.3)
// [v1.3] 더보기 방식 → 페이지 번호 방식 (10건/페이지)
// ============================================================

import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { ExternalLink } from "lucide-react";
import { SpamLog } from "@/lib/types";
import Pagination from "@/components/ui/Pagination";

interface SpamListProps {
  logs:         SpamLog[];
  isLoading:    boolean;
  currentPage:  number;
  totalPages:   number;
  onPageChange: (page: number) => void;
}

export default function SpamList({
  logs, isLoading, currentPage, totalPages, onPageChange
}: SpamListProps) {
  return (
    <div className="card animate-enter">
      <div className="flex items-center justify-between mb-4">
        <p className="section-title mb-0">스팸 삭제 목록</p>
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
          🎉 삭제된 스팸 댓글이 없습니다.
        </p>
      )}

      {!isLoading && logs.length > 0 && (
        <>
          <div className="space-y-2">
            {logs.map((log) => {
              const deletedAt     = format(new Date(log.deleted_at), "MM/dd HH:mm", { locale: ko });
              const confidencePct = log.ai_confidence
                ? `${(log.ai_confidence * 100).toFixed(0)}%`
                : null;

              return (
                <div
                  key={log.id}
                  className="px-3 py-2.5 rounded-lg bg-[#0D1117] border border-[#3D0A0A] hover:border-[#F85149]/40 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-xs font-semibold text-[#F85149] shrink-0">
                        {log.comment_author}
                      </span>
                      {log.keyword_matched && (
                        <span className="text-xs bg-[#3D0A0A] text-[#F85149] px-1.5 py-0.5 rounded border border-[#F85149]/20 shrink-0">
                          키워드: {log.keyword_matched}
                        </span>
                      )}
                      {confidencePct && (
                        <span className="text-xs text-[#8B949E] shrink-0">AI {confidencePct}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="font-stat text-xs text-[#484F58]">{deletedAt}</span>
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
