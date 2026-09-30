export function fmtClock(ms: number | null | undefined): string {
  if (ms == null) return "–:––";
  const total = Math.ceil(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function fmtElapsed(ms: number | null | undefined): string {
  if (ms == null) return "–";
  const t = Math.floor(ms / 1000);
  return `${Math.floor(t / 60)}:${(t % 60).toString().padStart(2, "0")}`;
}

export function fmtPoints(n: number | null | undefined): string {
  return n == null ? "–" : n.toLocaleString("en-GB");
}

export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

/** Benchmark time; anything under the floor is shown as "≤ floor" (it scores the same). */
export function fmtBenchMs(ms: number | null | undefined, floor = 0): string {
  if (ms == null) return "–";
  return floor > 0 && ms <= floor ? `≤ ${floor} ms` : `${Math.round(ms).toLocaleString("en-GB")} ms`;
}

export const TYPE_ACCENT: Record<string, string> = {
  multiple_choice: "#F6B73C",
  super_fast: "#EF4E6B",
  code_golf: "#2E86DE",
  best_complexity: "#21A68D",
};
