"use client";
import { animate, AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { fmtPoints } from "@/lib/format";
import { useGame } from "@/lib/store";
import type { BoardRow } from "@/lib/types";

function CountUp({ from, to }: { from: number; to: number }) {
  const [v, setV] = useState(from);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) {
      setV(to);
      return;
    }
    const c = animate(from, to, { duration: 1.2, ease: "easeOut", onUpdate: (x) => setV(Math.round(x)) });
    return () => c.stop();
  }, [from, to, reduce]);
  return <>{fmtPoints(v)}</>;
}

export function Leaderboard({ rows, limit = 10, highlight, title = "Leaderboard", compact = false }: { rows: BoardRow[]; limit?: number; highlight?: string; title?: string; compact?: boolean }) {
  const adjustments = useGame((s) => s.adjustments);
  const [badges, setBadges] = useState<Record<string, { text: string; key: number; negative: boolean }>>({});
  const seen = useRef(adjustments.length ? adjustments[adjustments.length - 1].n : 0);
  const [order, setOrder] = useState<BoardRow[]>(() =>
    // start in the previous order, then slide into the new one
    [...rows].sort((a, b) => (a.prev_rank ?? a.rank) - (b.prev_rank ?? b.rank)),
  );

  // Snapshots arrive often; only replay the animation when the standings actually change.
  const contentKey = JSON.stringify(rows.map((r) => [r.team_id, r.name, r.points, r.rank, r.prev_rank]));
  useEffect(() => {
    const current: BoardRow[] = JSON.parse(contentKey).map(([team_id, name, points, rank, prev_rank]: [string, string, number, number, number | null]) => ({
      ...rows.find((r) => r.team_id === team_id),
      team_id,
      name,
      points,
      rank,
      prev_rank,
    }));
    setOrder([...current].sort((a, b) => (a.prev_rank ?? a.rank) - (b.prev_rank ?? b.rank)));
    const t = setTimeout(() => setOrder([...current].sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name))), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contentKey]);

  useEffect(() => {
    const fresh = adjustments.filter((a) => a.n > seen.current);
    if (adjustments.length) seen.current = adjustments[adjustments.length - 1].n;
    if (!fresh.length) return;
    setBadges((b) => {
      const next = { ...b };
      for (const a of fresh) next[a.team_id] = { text: `${a.delta > 0 ? "+" : ""}${a.delta}${a.show_note && a.note ? ` ${a.note}` : a.delta > 0 ? " bonus" : ""}`, key: Date.now(), negative: a.delta < 0 };
      return next;
    });
  }, [adjustments]);

  const shown = order.slice(0, limit);
  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      <h1 className={`text-center font-stage font-black text-white ${compact ? "text-3xl" : "text-6xl"}`}>{title}</h1>
      <ol className={`mx-auto max-w-4xl ${compact ? "space-y-1.5" : "space-y-3"}`}>
        <AnimatePresence initial={false}>
          {shown.map((r) => {
            const moved = r.prev_rank != null ? r.prev_rank - r.rank : 0;
            return (
              <motion.li
                key={r.team_id}
                layout
                transition={{ type: "spring", stiffness: 300, damping: 25 }}
                className={`relative flex items-center gap-4 rounded-lg px-5 font-stage font-extrabold shadow-lg ${compact ? "py-2 text-lg" : "py-3 text-3xl"} ${
                  r.team_id === highlight ? "bg-accent text-black" : "bg-white text-stage-deep"
                }`}
              >
                <span className="w-10 text-center font-black">{r.rank}</span>
                <span className="w-8 text-center text-xl" aria-label={moved > 0 ? `up ${moved}` : moved < 0 ? `down ${-moved}` : "no change"}>
                  {moved > 0 ? <span className="text-pass">▲</span> : moved < 0 ? <span className="text-fail">▼</span> : ""}
                </span>
                <span className="min-w-0 flex-1 truncate">{r.name}</span>
                {badges[r.team_id] && (
                  <motion.span
                    key={badges[r.team_id].key}
                    initial={{ opacity: 0, scale: 0.5 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className={`rounded-full px-3 py-0.5 text-base font-black text-white ${badges[r.team_id].negative ? "bg-fail" : "bg-round-green"}`}
                  >
                    {badges[r.team_id].text}
                  </motion.span>
                )}
                <span className="tabular-nums">
                  <CountUp from={r.prev_points ?? r.points} to={r.points} />
                </span>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ol>
    </div>
  );
}
