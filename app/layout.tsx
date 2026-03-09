// ============================================================
// 파일명: layout.tsx
// 경로:   cafe-bot-dashboard/app/layout.tsx
// 역할:   Next.js 루트 레이아웃 — 메타데이터, 폰트, 전역 스타일
// 작성일: 2026-03-10
// ============================================================

import type { Metadata, Viewport } from "next";
import "./globals.css";

// ── 메타데이터 ───────────────────────────────────────────────
export const metadata: Metadata = {
  title: "알렉스강 카페봇 대시보드",
  description: "네이버 카페 자동 관리봇 모니터링 대시보드",
  // 모바일 홈화면 추가 시 앱처럼 보이도록
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "카페봇",
  },
};

// ── 뷰포트 설정 (모바일 최적화) ──────────────────────────────
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1, // 모바일 줌 방지
  themeColor: "#0D1117",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>
        {/* 전체 페이지 최소 높이 보장 */}
        <div className="min-h-screen bg-[#0D1117]">
          {children}
        </div>
      </body>
    </html>
  );
}
