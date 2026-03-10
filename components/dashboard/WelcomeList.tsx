// ============================================================
// 파일명: WelcomeList.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/WelcomeList.tsx
// 역할:   작성된 환영 댓글 전체 누적 목록 (더보기 페이지네이션)
//
// 수정일: 2026-03-11 (v1.2)
// [v1.2]
//   - 최근 20건 고정 → 전체 누적 + "더보기" 버튼
//   - totalCount / hasMore / onLoadMore prop 추가
// ============================================================

import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { ExternalLink } from "lucide-react";
import { WelcomeLog } from "@/lib/types";

interface WelcomeListProps {
  logs:        WelcomeLog[];
  totalCount:  number;
  isLoading:   boolean;
  hasMore:     boolean;
  onLoadMore:  () => void;
}

export default function WelcomeList({
  logs, totalCount, isLoading, hasMore, onLoadMore
}: WelcomeListProps) {
  return (
    <div className="card animate-enter">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-4">
        <p className="section-title mb-0">환영 댓글 목록</p>
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
          작성된 환영 댓글이 없습니다.
        </p>
      )}

      {/* 목록 */}
      {!isLoading && logs.length > 0 && (
        <>
          <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
            {logs.map((log) => {
              const commentedAt = format(new Date(log.commented_at), "MM/dd HH:mm", { locale: ko });

              return (
                <div
                  key={log.id}
                  className="
                    px-3 py-2.5 rounded-lg
                    bg-[#0D1117] border border-[#1A4A2A]
                    hover:border-[#3FB950]/40 transition-colors
                  "
                >
                  {/* 첫째 줄: 작성자 + 시각 + 링크 */}
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-semibold text-[#3FB950]">
                      {log.post_author}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="font-stat text-xs text-[#484F58]">{commentedAt}</span>
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
