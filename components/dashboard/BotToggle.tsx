// ============================================================
// 파일명: BotToggle.tsx
// 경로:   cafe-bot-dashboard/components/dashboard/BotToggle.tsx
// 역할:   봇 수동 실행 트리거 버튼 + 마지막 실행 상태 표시
//
// 동작:
//   - 버튼 클릭 → /api/trigger-bot POST → GitHub Actions workflow_dispatch
//   - 실행 중 로딩 스피너 표시 (중복 클릭 방지)
//   - 성공/실패 토스트 메시지
//
// 작성일: 2026-03-10
// ============================================================

"use client";

import { useState } from "react";
import { Play, Loader2 } from "lucide-react";
import Badge from "@/components/ui/Badge";
import { BotRunLog } from "@/lib/types";

interface BotToggleProps {
  lastRun:   BotRunLog | null;
  onTriggered: () => void; // 트리거 성공 후 데이터 새로고침
}

export default function BotToggle({ lastRun, onTriggered }: BotToggleProps) {
  const [isTriggering, setIsTriggering] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // 마지막 실행 상태 → Badge variant 변환
  const statusVariant = () => {
    if (!lastRun) return "neutral";
    switch (lastRun.status) {
      case "success":       return "success";
      case "partial_error": return "warning";
      case "failed":        return "error";
      default:              return "neutral";
    }
  };

  const statusLabel = () => {
    if (!lastRun) return "실행 이력 없음";
    switch (lastRun.status) {
      case "success":       return "정상 완료";
      case "partial_error": return "부분 오류";
      case "failed":        return "실패";
      default:              return "알 수 없음";
    }
  };

  // GitHub Actions 수동 트리거
  const handleTrigger = async () => {
    if (isTriggering) return;
    setIsTriggering(true);
    setMessage(null);

    try {
      const res = await fetch("/api/trigger-bot", { method: "POST" });
      const data = await res.json();

      if (res.ok && data.success) {
        setMessage({ type: "success", text: "봇 실행이 요청되었습니다. 약 1~2분 후 결과가 반영됩니다." });
        // 10초 후 데이터 새로고침
        setTimeout(() => {
          onTriggered();
          setMessage(null);
        }, 10000);
      } else {
        setMessage({ type: "error", text: data.message ?? "실행 요청 실패" });
      }
    } catch {
      setMessage({ type: "error", text: "네트워크 오류 — 잠시 후 다시 시도해 주세요." });
    } finally {
      setIsTriggering(false);
    }
  };

  return (
    <div className="card animate-enter">
      <p className="section-title">봇 제어</p>

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        {/* 마지막 실행 상태 */}
        <div className="flex items-center gap-3">
          <Badge variant={statusVariant()} dot>
            {statusLabel()}
          </Badge>
          {lastRun && (
            <span className="text-xs text-[#8B949E]">
              스팸 {lastRun.spam_deleted}건 · 환영 {lastRun.welcome_commented}건
            </span>
          )}
        </div>

        {/* 수동 실행 버튼 */}
        <button
          onClick={handleTrigger}
          disabled={isTriggering}
          className="
            flex items-center justify-center gap-2
            w-full sm:w-auto
            px-4 py-2.5
            bg-[#2EA043] hover:bg-[#3FB950]
            disabled:bg-[#1A4A2A] disabled:cursor-not-allowed
            text-white text-sm font-semibold
            rounded-lg transition-colors duration-200
          "
        >
          {isTriggering ? (
            <>
              <Loader2 size={15} className="animate-spin" />
              실행 중...
            </>
          ) : (
            <>
              <Play size={15} />
              지금 실행
            </>
          )}
        </button>
      </div>

      {/* 메시지 */}
      {message && (
        <p
          className={`
            mt-3 text-xs px-3 py-2 rounded-lg
            ${message.type === "success"
              ? "bg-[#1A4A2A] text-[#3FB950]"
              : "bg-[#3D0A0A] text-[#F85149]"
            }
          `}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}
