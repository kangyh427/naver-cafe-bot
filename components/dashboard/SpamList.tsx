// ============================================================
// 파일명: SpamList.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/SpamList.tsx
// 역할:   삭제된 스팸 댓글 전체 누적 목록 (더보기 페이지네이션)
//
// 수정일: 2026-03-11 (v1.2)
// [v1.2]
//   - 최근 20건 고정 → 전체 누적 + "더보기" 버튼
//   - totalCount / hasMore / onLoadMore prop 추가
// ============================================================

import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { ExternalLink } from "lucide-react";
import { SpamLog } from "@/lib/types";

interface SpamListProps {
  logs:        SpamLog[];
  totalCount:  number;
  isLoading:   boolean;
  hasMore:     boolean;
  onLoadMore:  () => void;
}

export default function SpamList({
  logs, totalCount, isLoading, hasMore, onLoadMore
}: SpamListProps) {
  return (
    <div className="card animate-enter">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-4">
        <p className="section-title mb-0">스팸 삭제 목록</p>
        <span className="font-stat text-xs text-[#8B949E]">
          누적 {totalCount.toLocaleString()}건
        </span>
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
        <>
          <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
            {logs.map((log) => {
              const deletedAt      = format(new Date(log.deleted_at), "MM/dd HH:mm", { locale: ko });
              const confidencePct  = log.ai_confidence
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
                  {/* 첫째 줄: 작성자 + 키워드 + 시각 + 링크 */}
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

          {/* 더보기 버튼 */}
          {hasMore && (
            <button
              onClick={onLoadMore}
              className="
                w-full mt-3 py-2 text-xs text-[#8B949E]
                bg-[#0D1117] border border-[#30363D] rounded-lg
                hover:text-[#E6EDF3] hover:border-[#484F58]
                transition-all duration-200
              "
            >
              더보기 ({logs.length} / {totalCount})
            </button>
          )}
        </>
      )}
    </div>
  );
}
