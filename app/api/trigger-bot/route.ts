// ============================================================
// 파일명: route.ts
// 경로:   cafe-bot-dashboard/app/api/trigger-bot/route.ts
// 역할:   GitHub Actions workflow_dispatch API 트리거
//
// 동작:
//   POST /api/trigger-bot
//   → GitHub API POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches
//   → 봇 즉시 1회 실행 요청
//
// 안전장치:
//   - GITHUB_TOKEN 누락 시 500 반환 (undefined behavior 방지)
//   - GitHub API 실패 시 상세 오류 메시지 반환
//   - 서버 사이드 전용 (GITHUB_TOKEN 클라이언트 노출 방지)
//
// 작성일: 2026-03-10
// ============================================================

import { NextResponse } from "next/server";

export async function POST() {
  // ── 환경변수 검증 ──────────────────────────────────────────
  const token      = process.env.GITHUB_TOKEN;
  const owner      = process.env.GITHUB_OWNER      ?? "kangyh427";
  const repo       = process.env.GITHUB_REPO       ?? "naver_cafe_bot";
  const workflowId = process.env.GITHUB_WORKFLOW_ID ?? "main.yml";

  if (!token) {
    return NextResponse.json(
      { success: false, message: "GITHUB_TOKEN 환경변수가 설정되지 않았습니다." },
      { status: 500 }
    );
  }

  // ── GitHub Actions API 호출 ────────────────────────────────
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowId}/dispatches`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization:  `Bearer ${token}`,
        Accept:         "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main" }), // main 브랜치에서 실행
    });

    // GitHub API는 성공 시 204 No Content 반환
    if (res.status === 204) {
      return NextResponse.json({ success: true, message: "봇 실행 요청 성공" });
    }

    // 실패 응답 처리
    const errorBody = await res.json().catch(() => ({}));
    const errorMsg  = (errorBody as { message?: string }).message ?? `HTTP ${res.status}`;

    return NextResponse.json(
      { success: false, message: `GitHub API 오류: ${errorMsg}` },
      { status: res.status }
    );

  } catch (err) {
    const message = err instanceof Error ? err.message : "알 수 없는 오류";
    return NextResponse.json(
      { success: false, message: `요청 실패: ${message}` },
      { status: 500 }
    );
  }
}
