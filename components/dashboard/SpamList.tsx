// ============================================================
// 파일명: SpamList.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/SpamList.tsx
// 역할:   삭제된 스팸 댓글 목록 (최근 20건)
// 작성일: 2026-03-10
// ============================================================

import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { ExternalLink } from "lucide-react";
import { SpamLog } from "@/lib/types";

interface SpamListProps {
  logs:      SpamLog[];
  isLoading: boolean;
}

export default function SpamList({ logs, isLoading }: SpamListProps) {
  return (
    <div className="card animate-enter">
      <div className="flex items-center justify-between mb-4">
        <p className="section-title mb-0">스팸 삭제 목록</p>
        <span className="font-stat text-xs text-[#8B949E]">최근 {logs.length}건</span>
      </div>

      {/* 로딩 스켈레톤 */}
      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-[#30363D] rounded-lg animate-pulse-soft" />
          ))}
        </div>
      )}

      {/* 데이터 없음 */}
      {!isLoading && logs.length === 0 && (
        <p className="text-sm text-[#484F58] text-center py-6">
          🎉 삭제된 스팸 댓글이 없습니다.
        </p>
      )}

      {/* 목록 */}
      {!isLoading && logs.length > 0 && (
        <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
          {logs.map((log) => {
            const deletedAt = format(new Date(log.deleted_at), "MM/dd HH:mm", { locale: ko });
            // 신뢰도 퍼센트 변환
            const confidencePct = log.ai_confidence
              ? `${(log.ai_confidence * 100).toFixed(0)}%`
              : null;

            return (
              <div
                key={log.id}
                className="
                  px-3 py-2.5 rounded-lg
                  bg-[#0D1117] border border-[#3D0A0A]
                  hover:border-[#F85149]/40 transition-colors
                "
              >
                {/* 첫째 줄: 작성자 + 시각 + 게시글 링크 */}
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
                      <span className="text-xs text-[#8B949E] shrink-0">
                        AI {confidencePct}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="font-stat text-xs text-[#484F58]">{deletedAt}</span>
                    <a
                      href={log.post_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[#484F58] hover:text-[#58A6FF] transition-colors"
                      aria-label="게시글 열기"
                    >
                      <ExternalLink size={12} />
                    </a>
                  </div>
                </div>

                {/* 둘째 줄: 댓글 내용 */}
                {log.comment_content && (
                  <p className="text-xs text-[#8B949E] line-clamp-2 leading-relaxed">
                    {log.comment_content}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
