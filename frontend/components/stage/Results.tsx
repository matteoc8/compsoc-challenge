"use client";
import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";
import { fmtBenchMs, fmtElapsed, fmtPoints, ordinal, TYPE_ACCENT } from "@/lib/format";
import { useGame } from "@/lib/store";
import type { Results as ResultsT } from "@/lib/types";

export function MeasuringSpeed() {
  const judging = useGame((s) => s.judging);
  const reduce = useReducedMotion();
  return (
    <div className="flex h-full flex-col items-center justify-center gap-8 text-center">
      <div className="relative h-40 w-40">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="absolute inset-0 rounded-full border-8 border-white/80"
            initial={{ scale: 0.4, opacity: 0.9 }}
            animate={reduce ? { opacity: 0.6 } : { scale: 1.3, opacity: 0 }}
            transition={{ duration: 1.8, repeat: Infinity, delay: i * 0.6, ease: "easeOut" }}
          />
        ))}
        <div className="absolute inset-0 flex items-center justify-center text-6xl" aria-hidden>
          ⏱
        </div>
      </div>
      <h1 className="font-stage text-6xl font-black text-white">Measuring speed…</h1>
      <p className="font-stage text-2xl font-bold text-white/80">
        Every correct solution runs on bigger and bigger inputs
        {judging && judging.total > 0 ? ` · ${judging.done} / ${judging.total} measured` : ""}
      </p>
    </div>
  );
}

function Row({ i, children, accent }: { i: number; children: React.ReactNode; accent: string }) {
  return (
    <motion.li
      initial={{ opacity: 0, x: -40 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.08 * i, type: "spring", stiffness: 300, damping: 25 }}
      className="flex items-center gap-4 rounded-lg bg-white px-5 py-3 font-stage text-2xl font-extrabold text-stage-deep shadow-lg"
    >
      <span className="w-14 text-center text-3xl font-black" style={{ color: accent }}>
        {ordinal(i + 1)}
      </span>
      {children}
    </motion.li>
  );
}

export function ResultsView({ results, compact = false, myTeamId }: { results: ResultsT; compact?: boolean; myTeamId?: string }) {
  const accent = TYPE_ACCENT[results.type];
  const rows = results.rows.slice(0, compact ? 20 : 8);
  return (
    <div className={`flex h-full flex-col ${compact ? "gap-4 p-6" : "gap-6 p-10"}`}>
      <div>
        <div className="font-stage text-xl font-bold uppercase tracking-widest text-white/70">{results.round_name} · results</div>
        <h1 className={`font-stage font-black text-white ${compact ? "text-3xl" : "text-5xl"}`}>{results.title}</h1>
      </div>
      <div className="flex min-h-0 flex-1 gap-8">
        <ol className="min-w-0 flex-1 space-y-3 overflow-y-auto">
          {rows.map((r, i) => (
            <Row key={r.team_id} i={i} accent={accent}>
              <span className={`flex-1 truncate ${r.team_id === myTeamId ? "underline decoration-4 underline-offset-4" : ""}`}>{r.name}</span>
              {results.type === "super_fast" && (
                <span className="text-lg font-bold text-stage-deep/60">
                  {r.first_full_ms != null ? `solved in ${fmtElapsed(r.first_full_ms)}` : r.passed != null ? `${r.passed}/${r.total} tests` : "no submission"}
                </span>
              )}
              {results.type === "code_golf" && <span className="text-lg font-bold text-stage-deep/60">{r.chars != null ? `${r.chars} chars` : "not passing"}</span>}
              {results.type === "best_complexity" && (
                <span className="text-right text-lg font-bold text-stage-deep/60">
                  {r.class_label ?? (r.passed != null ? "not passing" : "no submission")}
                  {r.time_ms != null && <span className="ml-3 tabular-nums">{fmtBenchMs(r.time_ms, results.floor_ms)}</span>}
                </span>
              )}
              <span className="w-28 text-right tabular-nums" style={{ color: accent }}>
                +{fmtPoints(r.points)}
              </span>
            </Row>
          ))}
          {!rows.length && <p className="font-stage text-2xl text-white/80">No teams took part.</p>}
        </ol>
        {results.type === "code_golf" && results.top3 && results.top3.length > 0 && !compact && <GolfReveal top3={results.top3} />}
      </div>
    </div>
  );
}

// Top 3 golf solutions revealed one by one, 3rd first.
export function GolfReveal({ top3 }: { top3: NonNullable<ResultsT["top3"]> }) {
  const [shown, setShown] = useState(0);
  const [html, setHtml] = useState<Record<number, string>>({});
  const order = [...top3.keys()].reverse();

  useEffect(() => {
    setShown(0);
    const timers = order.map((_, k) => setTimeout(() => setShown(k + 1), 1500 + k * 2500));
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [top3.length]);

  useEffect(() => {
    let cancelled = false;
    import("shiki")
      .then(async ({ codeToHtml }) => {
        const out: Record<number, string> = {};
        for (let i = 0; i < top3.length; i++) out[i] = await codeToHtml(top3[i].code, { lang: "python", theme: "github-light" });
        if (!cancelled) setHtml(out);
      })
      .catch(() => undefined); // fall back to plain text
    return () => {
      cancelled = true;
    };
  }, [top3]);

  return (
    <div className="flex w-[46%] shrink-0 flex-col gap-4 overflow-y-auto">
      <h2 className="font-stage text-2xl font-black text-white">Shortest solutions</h2>
      {order.slice(0, shown).map((i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 30, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          className="rounded-xl bg-white p-4 shadow-xl"
        >
          <div className="mb-2 flex items-baseline justify-between font-stage font-black text-stage-deep">
            <span className="text-2xl">
              {ordinal(i + 1)} {top3[i].name}
            </span>
            <span className="text-xl text-round-blue">{top3[i].chars} chars</span>
          </div>
          {html[i] ? (
            <div className="golf-code overflow-x-auto text-lg" dangerouslySetInnerHTML={{ __html: html[i] }} />
          ) : (
            <pre className="overflow-x-auto whitespace-pre font-mono text-lg text-stage-deep">{top3[i].code}</pre>
          )}
        </motion.div>
      ))}
    </div>
  );
}
