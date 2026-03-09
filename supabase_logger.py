"""
supabase_logger.py
Supabase DB 연동 - 로그 저장 및 처리 기록 관리
- 스팸 삭제 로그
- 환영 댓글 로그
- 처리된 게시글 URL 추적 (중복 방지)
- 봇 실행 로그
"""

import os
from datetime import datetime
from supabase import create_client, Client


class SupabaseLogger:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")

        if not url or not key:
            raise ValueError("SUPABASE_URL 또는 SUPABASE_SERVICE_KEY 환경변수 없음")

        self.client: Client = create_client(url, key)
        print("[DB] Supabase 연결 성공")

    async def get_processed_urls(self) -> set:
        """처리 완료된 게시글 URL 목록 조회 (중복 방지용)"""
        try:
            response = self.client.table("processed_posts").select("post_url").execute()
            urls = {row["post_url"] for row in response.data}
            print(f"[DB] 처리된 게시글 {len(urls)}개 로드")
            return urls
        except Exception as e:
            print(f"[DB] URL 조회 오류: {e}")
            return set()

    async def mark_post_processed(self, post_url: str, post_type: str = "welcome"):
        """게시글을 처리 완료로 표시"""
        try:
            self.client.table("processed_posts").upsert({
                "post_url": post_url,
                "post_type": post_type,
                "processed_at": datetime.utcnow().isoformat(),
            }).execute()
        except Exception as e:
            print(f"[DB] 처리 표시 오류: {e}")

    async def log_spam_deleted(
        self,
        content_type: str,     # 'comment' or 'post'
        author: str,
        content: str,
        reason: str,
        post_url: str,
        detected_keyword: str = "",
        ai_confidence: float = 0.0,
    ):
        """스팸 삭제 로그 저장"""
        try:
            self.client.table("spam_logs").insert({
                "type": content_type,
                "author": author,
                "content": content[:500],   # 최대 500자
                "reason": reason,
                "post_url": post_url,
                "detected_keyword": detected_keyword,
                "ai_confidence": ai_confidence,
                "deleted_at": datetime.utcnow().isoformat(),
            }).execute()
            print(f"[DB] 스팸 로그 저장: {author} - {content[:30]}...")
        except Exception as e:
            print(f"[DB] 스팸 로그 저장 오류: {e}")

    async def log_welcome_comment(
        self,
        post_title: str,
        post_url: str,
        author: str,
        welcome_message: str,
        post_type: str = "일반",
    ):
        """환영 댓글 로그 저장"""
        try:
            self.client.table("welcome_logs").insert({
                "post_title": post_title[:200],
                "post_url": post_url,
                "author": author,
                "welcome_message": welcome_message[:500],
                "post_type": post_type,
                "commented_at": datetime.utcnow().isoformat(),
            }).execute()
            print(f"[DB] 환영 댓글 로그 저장: {author} - {post_title[:30]}...")
        except Exception as e:
            print(f"[DB] 환영 댓글 로그 저장 오류: {e}")

    async def log_bot_run(
        self,
        status: str,
        posts_checked: int = 0,
        comments_checked: int = 0,
        spam_deleted: int = 0,
        welcome_sent: int = 0,
        error_message: str = "",
    ):
        """봇 실행 로그 저장"""
        try:
            self.client.table("bot_run_logs").insert({
                "run_at": datetime.utcnow().isoformat(),
                "status": status,
                "posts_checked": posts_checked,
                "comments_checked": comments_checked,
                "spam_deleted": spam_deleted,
                "welcome_sent": welcome_sent,
                "error_message": error_message[:500] if error_message else "",
            }).execute()
            print(
                f"[DB] 실행 로그 저장: {status} | "
                f"게시글 {posts_checked}개 | 스팸삭제 {spam_deleted}개 | "
                f"환영댓글 {welcome_sent}개"
            )
        except Exception as e:
            print(f"[DB] 실행 로그 저장 오류: {e}")
