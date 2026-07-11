import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#18211d",
        paper: "#f5f1e8",
        moss: "#2e5c45",
        clay: "#b85535",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Fraunces", "Noto Serif SC", "ui-serif", "serif"],
      },
      boxShadow: {
        soft: "0 18px 60px rgba(32, 45, 38, 0.10)",
      },
    },
  },
  plugins: [],
} satisfies Config;
