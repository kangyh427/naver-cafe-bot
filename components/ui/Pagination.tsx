// ============================================================
// 파일명: Pagination.tsx
// 경로:   cafe-bot-dashboard/components/ui/Pagination.tsx
// 역할:   페이지 번호 방식 공통 페이지네이션 컴포넌트
//
// 작성일: 2026-03-11 (v1.0)
// ============================================================

interface PaginationProps {
  currentPage: number;
  totalPages:  number;
  onPageChange: (page: number) => void;
}

export default function Pagination({ currentPage, totalPages, onPageChange }: PaginationProps) {
  if (totalPages <= 1) return null;

  // 표시할 페이지 번호 범위 계산 (현재 페이지 중심으로 최대 5개)
  const getPageNumbers = () => {
    const delta = 2;
    const range: number[] = [];
    const rangeStart = Math.max(1, currentPage - delta);
    const rangeEnd   = Math.min(totalPages, currentPage + delta);
    for (let i = rangeStart; i <= rangeEnd; i++) range.push(i);
    return range;
  };

  const pages = getPageNumbers();

  return (
    <div className="flex items-center justify-center gap-1 mt-3">
      {/* 이전 버튼 */}
      <button
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
        className="w-7 h-7 flex items-center justify-center rounded text-[#8B949E] bg-[#0D1117] border border-[#30363D] hover:border-[#484F58] hover:text-[#E6EDF3] disabled:opacity-30 disabled:cursor-not-allowed transition-all text-xs"
      >
        ‹
      </button>

      {/* 첫 페이지 + 생략 */}
      {pages[0] > 1 && (
        <>
          <button
            onClick={() => onPageChange(1)}
            className="w-7 h-7 flex items-center justify-center rounded text-xs text-[#8B949E] bg-[#0D1117] border border-[#30363D] hover:border-[#484F58] hover:text-[#E6EDF3] transition-all"
          >
            1
          </button>
          {pages[0] > 2 && (
            <span className="text-[#484F58] text-xs px-1">…</span>
          )}
        </>
      )}

      {/* 페이지 번호 */}
      {pages.map(page => (
        <button
          key={page}
          onClick={() => onPageChange(page)}
          className={`
            w-7 h-7 flex items-center justify-center rounded text-xs font-stat transition-all
            ${page === currentPage
              ? "bg-[#2EA043] text-white border border-[#2EA043]"
              : "text-[#8B949E] bg-[#0D1117] border border-[#30363D] hover:border-[#484F58] hover:text-[#E6EDF3]"
            }
          `}
        >
          {page}
        </button>
      ))}

      {/* 마지막 페이지 + 생략 */}
      {pages[pages.length - 1] < totalPages && (
        <>
          {pages[pages.length - 1] < totalPages - 1 && (
            <span className="text-[#484F58] text-xs px-1">…</span>
          )}
          <button
            onClick={() => onPageChange(totalPages)}
            className="w-7 h-7 flex items-center justify-center rounded text-xs text-[#8B949E] bg-[#0D1117] border border-[#30363D] hover:border-[#484F58] hover:text-[#E6EDF3] transition-all"
          >
            {totalPages}
          </button>
        </>
      )}

      {/* 다음 버튼 */}
      <button
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
        className="w-7 h-7 flex items-center justify-center rounded text-[#8B949E] bg-[#0D1117] border border-[#30363D] hover:border-[#484F58] hover:text-[#E6EDF3] disabled:opacity-30 disabled:cursor-not-allowed transition-all text-xs"
      >
        ›
      </button>
    </div>
  );
}
