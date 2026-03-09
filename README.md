# 알렉스강의 주식이야기 - 네이버 카페 자동 관리봇

## 기능
- 🗑️ 스팸/광고 댓글 자동 감지 및 삭제 (Gemini AI + 키워드 필터)
- 💬 신규 게시글 환영 댓글 자동 작성 (AI 개인화)
- 📊 Supabase DB에 모든 처리 내역 기록

## 기술 스택
- Python 3.11 + Playwright (브라우저 자동화)
- Gemini 1.5 Flash API (스팸 판별 + 댓글 생성)
- Supabase (로그 저장)
- GitHub Actions (30분마다 자동 실행)

## GitHub Secrets 설정 필수
| 키 | 값 |
|---|---|
| NAVER_ID | kangyh427 |
| NAVER_PW | 네이버 비밀번호 |
| SUPABASE_URL | https://cvvurdxdxfayijmmzcwt.supabase.co |
| SUPABASE_SERVICE_KEY | Supabase Secret key |
| GEMINI_API_KEY | Gemini API 키 |
| CAFE_ID | alexstock |
| CAFE_URL | https://cafe.naver.com/alexstock |

## 설정 방법
1. GitHub 레포 → Settings → Secrets and variables → Actions
2. 위 7개 항목을 모두 등록
3. Actions 탭에서 수동 실행으로 테스트
