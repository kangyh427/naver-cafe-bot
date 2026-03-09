"""
main.py
네이버 카페 자동 관리 봇 - 메인 실행 파일
GitHub Actions에서 30분마다 자동 실행

실행 흐름:
1. 네이버 로그인
2. 최신 게시글 목록 수집
3. 각 게시글 댓글 스팸 검사 → 삭제
4. 신규 게시글 환영 댓글 작성
5. Supabase에 로그 저장
"""

import asyncio
import sys
import os
from dotenv import load_dotenv

# 로컬 개발 시 .env 로드 (GitHub Actions에서는 Secrets 사용)
load_dotenv()

from naver_login import NaverLoginManager
from cafe_monitor import CafeMonitor
from spam_detector import SpamDetector
from comment_writer import CommentWriter
from supabase_logger import SupabaseLogger


async def main():
    """메인 봇 실행 함수"""
    print("=" * 50)
    print("🤖 알렉스강의 주식이야기 카페 관리봇 시작")
    print("=" * 50)

    # 통계 초기화
    stats = {
        "posts_checked": 0,
        "comments_checked": 0,
        "spam_deleted": 0,
        "welcome_sent": 0,
    }

    # 모듈 초기화
    login_manager = NaverLoginManager()
    db_logger = SupabaseLogger()
    spam_detector = SpamDetector()

    try:
        # ── 1. 브라우저 초기화 및 로그인 ──
        page = await login_manager.init_browser()
        login_success = await login_manager.login()

        if not login_success:
            print("[MAIN] ❌ 로그인 실패 - 봇 종료")
            await db_logger.log_bot_run(
                status="error",
                error_message="네이버 로그인 실패",
            )
            return

        await login_manager.verify_cafe_access()

        # ── 2. 모니터/라이터 초기화 ──
        cafe_monitor = CafeMonitor(page)
        comment_writer = CommentWriter(page)

        # ── 3. 처리된 게시글 URL 로드 (중복 방지) ──
        processed_urls = await db_logger.get_processed_urls()

        # ── 4. 최신 게시글 수집 ──
        posts = await cafe_monitor.get_recent_posts(max_posts=15)
        stats["posts_checked"] = len(posts)
        print(f"\n[MAIN] 총 {len(posts)}개 게시글 처리 시작\n")

        # ── 5. 각 게시글 처리 ──
        for post in posts:
            post_url = post.get("url", "")
            post_title = post.get("title", "")
            post_author = post.get("author", "")

            print(f"\n--- 게시글: {post_title[:40]}... ---")

            try:
                # 5-1. 해당 게시글의 댓글 수집 및 스팸 검사
                comments = await cafe_monitor.get_comments_from_post(post_url)
                stats["comments_checked"] += len(comments)

                for comment in comments:
                    content = comment.get("content", "")
                    author = comment.get("author", "")
                    idx = comment.get("index", 0)

                    # 관리자 댓글은 검사 안 함
                    if author in ["AlexKang", "알렉스", "alexkang"]:
                        continue

                    # 스팸 판별
                    should_delete, confidence, reason, keyword = (
                        await spam_detector.is_spam(content)
                    )

                    if should_delete:
                        print(
                            f"[MAIN] 🗑️ 스팸 삭제: {author} - "
                            f"'{content[:30]}...' (확신도: {confidence:.0%})"
                        )

                        # 댓글 삭제
                        deleted = await cafe_monitor.delete_comment(post_url, idx)

                        if deleted:
                            stats["spam_deleted"] += 1
                            await db_logger.log_spam_deleted(
                                content_type="comment",
                                author=author,
                                content=content,
                                reason=reason,
                                post_url=post_url,
                                detected_keyword=keyword,
                                ai_confidence=confidence,
                            )

                # 5-2. 신규 게시글 환영 댓글 작성
                welcome_msg = await comment_writer.process_new_post(
                    post=post,
                    processed_urls=processed_urls,
                )

                if welcome_msg:
                    stats["welcome_sent"] += 1
                    # 처리 완료 표시 (중복 방지)
                    await db_logger.mark_post_processed(post_url, "welcome")
                    processed_urls.add(post_url)  # 메모리에도 추가

                    await db_logger.log_welcome_comment(
                        post_title=post_title,
                        post_url=post_url,
                        author=post_author,
                        welcome_message=welcome_msg,
                        post_type=post.get("board", "일반"),
                    )

            except Exception as e:
                print(f"[MAIN] 게시글 처리 오류: {post_title[:30]}... - {e}")
                continue

        # ── 6. 성공 로그 저장 ──
        await db_logger.log_bot_run(
            status="success",
            **stats,
        )

        print("\n" + "=" * 50)
        print(f"✅ 봇 실행 완료!")
        print(f"   - 게시글 확인: {stats['posts_checked']}개")
        print(f"   - 댓글 확인: {stats['comments_checked']}개")
        print(f"   - 스팸 삭제: {stats['spam_deleted']}개")
        print(f"   - 환영 댓글: {stats['welcome_sent']}개")
        print("=" * 50)

    except Exception as e:
        print(f"\n[MAIN] ❌ 봇 실행 오류: {e}")
        await db_logger.log_bot_run(
            status="error",
            error_message=str(e),
            **stats,
        )
        sys.exit(1)

    finally:
        await login_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
