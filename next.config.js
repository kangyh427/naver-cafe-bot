/** @type {import('next').NextConfig} */
const nextConfig = {
  // App Router 기본 사용
  reactStrictMode: true,

  // 환경변수 클라이언트 노출 허용 목록
  // NEXT_PUBLIC_ 접두사가 있는 변수는 자동으로 클라이언트에 노출됨
  env: {
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  },
};

module.exports = nextConfig;
