/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // ── 커스텀 컬러 팔레트 ──────────────────────────────
      colors: {
        // 메인 배경 (다크 네이비 계열)
        bg: {
          primary:   "#0D1117",
          secondary: "#161B22",
          card:      "#1C2128",
          border:    "#30363D",
        },
        // 텍스트
        text: {
          primary:   "#E6EDF3",
          secondary: "#8B949E",
          muted:     "#484F58",
        },
        // 액센트 (네이버 그린 계열)
        accent: {
          green:     "#2EA043",
          greenHover:"#3FB950",
          greenDim:  "#1A4A2A",
        },
        // 상태 컬러
        status: {
          success:   "#3FB950",
          warning:   "#D29922",
          error:     "#F85149",
          info:      "#58A6FF",
        },
      },

      // ── 폰트 ──────────────────────────────────────────
      fontFamily: {
        // 본문: Pretendard (한국어 최적화)
        sans: ["Pretendard", "Apple SD Gothic Neo", "sans-serif"],
        // 숫자/코드: JetBrains Mono
        mono: ["JetBrains Mono", "monospace"],
      },

      // ── 애니메이션 ──────────────────────────────────────
      keyframes: {
        fadeIn: {
          "0%":   { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulse_soft: {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.5" },
        },
      },
      animation: {
        "fade-in":    "fadeIn 0.4s ease-out forwards",
        "pulse-soft": "pulse_soft 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
