// ============================================================
// 파일명: Badge.tsx
// 경로:   cafe-bot-dashboard/components/ui/Badge.tsx
// 역할:   상태 표시 뱃지 공통 컴포넌트 (success/warning/error/info)
// 작성일: 2026-03-10
// ============================================================

interface BadgeProps {
  variant: "success" | "warning" | "error" | "info" | "neutral";
  children: React.ReactNode;
  dot?: boolean; // 앞에 점 표시 여부
}

// variant별 스타일 맵
const STYLES: Record<BadgeProps["variant"], string> = {
  success: "bg-[#1A4A2A] text-[#3FB950] border-[#2EA043]/40",
  warning: "bg-[#3D2E0A] text-[#D29922] border-[#D29922]/40",
  error:   "bg-[#3D0A0A] text-[#F85149] border-[#F85149]/40",
  info:    "bg-[#0A1F3D] text-[#58A6FF] border-[#58A6FF]/40",
  neutral: "bg-[#1C2128] text-[#8B949E] border-[#30363D]",
};

const DOT_COLORS: Record<BadgeProps["variant"], string> = {
  success: "bg-[#3FB950]",
  warning: "bg-[#D29922]",
  error:   "bg-[#F85149]",
  info:    "bg-[#58A6FF]",
  neutral: "bg-[#8B949E]",
};

export default function Badge({ variant, children, dot = false }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-1.5
        px-2 py-0.5 rounded-full
        text-xs font-medium border
        ${STYLES[variant]}
      `}
    >
      {dot && (
        <span
          className={`w-1.5 h-1.5 rounded-full ${DOT_COLORS[variant]}`}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
