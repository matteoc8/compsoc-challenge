"use client";
import { useEffect, useRef } from "react";
import { fmtClock, fmtElapsed } from "@/lib/format";
import { countsUp, elapsedMs, remainingMs } from "@/lib/socket";
import { tick } from "@/lib/sound";
import { useGame } from "@/lib/store";
import { useNow } from "@/lib/useNow";

/** The question clock: a countdown, or (unlimited time) the time elapsed so far. */
export function useRemaining(): { ms: number | null; total: number; countUp: boolean; elapsed: number | null } {
  useNow(200);
  const game = useGame((s) => s.snapshot?.game);
  const q = useGame((s) => s.snapshot?.question);
  const offset = useGame((s) => s.offset);
  if (!game) return { ms: null, total: 1, countUp: false, elapsed: null };
  const total = (game.duration_s ?? q?.time_limit_s ?? 240) * 1000;
  return { ms: remainingMs(game, offset), total, countUp: countsUp(game), elapsed: elapsedMs(game, offset) };
}

export function InlineCountdown({ className = "" }: { className?: string }) {
  const { ms, total, countUp, elapsed } = useRemaining();
  const game = useGame((s) => s.snapshot?.game);
  if (countUp)
    return (
      <span className={`font-mono text-lg font-bold tabular-nums ${game?.paused ? "text-round-yellow" : "text-white"} ${className}`} aria-label="Time elapsed, no time limit" title="No time limit: the host ends this question">
        {game?.paused ? "⏸ " : "⏱ "}
        {fmtElapsed(elapsed)}
        <span className="ml-1.5 align-middle text-[0.55em] font-semibold uppercase tracking-wide text-ink-300">no limit</span>
      </span>
    );
  // "low" = the last 30 s, or the last quarter of a short question
  const low = ms != null && ms <= Math.min(30_000, total / 4);
  return (
    <span
      className={`font-mono text-lg font-bold tabular-nums ${game?.paused ? "text-round-yellow" : low ? "text-fail" : "text-white"} ${className}`}
      aria-label="Time remaining"
    >
      {game?.paused ? "⏸ " : ""}
      {fmtClock(ms)}
    </span>
  );
}

export function RingCountdown({ size = 260, sound = false }: { size?: number; sound?: boolean }) {
  const { ms, total, countUp, elapsed } = useRemaining();
  const game = useGame((s) => s.snapshot?.game);
  const lastTick = useRef<number | null>(null);
  const secs = ms == null ? null : Math.ceil(ms / 1000);

  useEffect(() => {
    if (!sound || secs == null || game?.paused || game?.state !== "open") return;
    if (secs <= 10 && secs >= 1 && lastTick.current !== secs) {
      lastTick.current = secs;
      tick(secs <= 3);
    }
  }, [secs, sound, game?.paused, game?.state]);

  const r = size / 2 - 14;
  const c = 2 * Math.PI * r;
  if (countUp)
    return (
      <div className="relative" style={{ width: size, height: size }} role="timer" aria-label={`${fmtElapsed(elapsed)} elapsed, no time limit`}>
        <svg width={size} height={size}>
          <circle cx={size / 2} cy={size / 2} r={r} stroke={game?.paused ? "#F0A03C" : "rgba(255,255,255,0.35)"} strokeWidth={16} fill="none" strokeDasharray="2 14" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center font-stage font-black text-white">
          <span style={{ fontSize: size * 0.26 }} className="tabular-nums leading-none">
            {fmtElapsed(elapsed)}
          </span>
          <span className="mt-2 text-xl font-extrabold text-ink-200">{game?.paused ? <span className="text-round-yellow">PAUSED</span> : "No time limit"}</span>
        </div>
      </div>
    );
  // total can grow when the host adds time; show the ring relative to whichever is larger
  const frac = ms == null ? 0 : Math.max(0, Math.min(1, ms / Math.max(total, ms)));
  const low = ms != null && ms <= 10_000;
  return (
    <div className="relative" style={{ width: size, height: size }} role="timer" aria-label={`${fmtClock(ms)} remaining`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(255,255,255,0.15)" strokeWidth={16} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={game?.paused ? "#F0A03C" : low ? "#F2545B" : "#ffffff"}
          strokeWidth={16}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - frac)}
          style={{ transition: "stroke-dashoffset 200ms linear" }}
        />
      </svg>
      <div className={`absolute inset-0 flex flex-col items-center justify-center font-stage font-black text-white ${low ? "animate-pulseRing" : ""}`}>
        <span style={{ fontSize: size * 0.26 }} className="tabular-nums leading-none">
          {fmtClock(ms)}
        </span>
        {game?.paused && <span className="mt-2 text-xl font-extrabold text-round-yellow">PAUSED</span>}
        {game?.ending && !game.paused && <span className="mt-2 text-xl font-extrabold text-round-yellow">Ending…</span>}
      </div>
    </div>
  );
}
