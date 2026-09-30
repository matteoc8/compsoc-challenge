import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Indigo stage with an amber accent (deliberately not Kahoot's purple or answer colours)
        stage: { DEFAULT: "#3226A0", deep: "#160F52" },
        accent: { DEFAULT: "#F6B73C", light: "#FFD27A", dark: "#C98C12" },
        pass: "#34C47C",
        fail: "#F2545B",
        round: { red: "#EF4E6B", blue: "#2E86DE", yellow: "#F0A03C", green: "#21A68D" },
        ink: { 900: "#0f1117", 800: "#161a23", 700: "#1e2330", 600: "#2a3142", 500: "#3a4358", 400: "#6b7690", 300: "#9aa4bb", 200: "#c9d0de" },
      },
      fontFamily: {
        stage: ["var(--font-stage)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        pop: { "0%": { transform: "scale(0.6)", opacity: "0" }, "70%": { transform: "scale(1.08)" }, "100%": { transform: "scale(1)", opacity: "1" } },
        pulseRing: { "0%,100%": { opacity: "0.35" }, "50%": { opacity: "1" } },
      },
      animation: { pop: "pop 300ms ease-out both", pulseRing: "pulseRing 1.2s ease-in-out infinite" },
    },
  },
  plugins: [],
};
export default config;
