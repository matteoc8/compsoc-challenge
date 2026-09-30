"use client";
import { AnimatePresence, motion } from "framer-motion";
import { fmtElapsed, ordinal } from "@/lib/format";
import type { Progress } from "@/lib/types";

// Super Fast: teams as they pass. Code Golf: best character count (never the code).
// Best Time Complexity: how many teams have a passing solution.
export function ProgressStrip({ progress }: { progress?: Progress }) {
  if (!progress) return null;
  if (progress.type === "super_fast") {
    const solves = progress.solves ?? [];
    return (
      <div className="flex min-h-[64px] flex-wrap items-center gap-3">
        {!solves.length && (
          <span className="font-stage text-2xl font-bold text-white/70">
            {progress.place_points ? `First ${progress.place_points.length} teams to solve it score…` : "No full solves yet…"}
          </span>
        )}
        <AnimatePresence>
          {solves.map((s, i) => (
            <motion.div
              key={s.team_id}
              layout
              initial={{ scale: 0.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
              className={`rounded-lg px-4 py-2 font-stage text-xl font-black text-white shadow-lg ${progress.place_points && i >= progress.place_points.length ? "bg-white/20" : "bg-pass"}`}
            >
              {ordinal(i + 1)} {s.name}{" "}
              <span className="ml-1 font-bold text-white/80">
                {progress.place_points ? (i < progress.place_points.length ? `+${progress.place_points[i].toLocaleString("en-GB")}` : "no points") : fmtElapsed(s.elapsed_ms)}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    );
  }
  if (progress.type === "code_golf") {
    return (
      <div className="flex items-center gap-6 font-stage text-white">
        <div>
          <div className="text-lg font-bold text-white/70">Shortest passing so far</div>
          <motion.div key={progress.best_chars ?? "none"} initial={{ scale: 1.4 }} animate={{ scale: 1 }} className="text-6xl font-black tabular-nums">
            {progress.best_chars ?? "–"} <span className="text-2xl font-bold">chars</span>
          </motion.div>
        </div>
        <div className="text-2xl font-extrabold text-white/80">
          {progress.passing} / {progress.teams_total} teams passing
        </div>
      </div>
    );
  }
  return (
    <div className="font-stage text-white">
      <div className="text-lg font-bold text-white/70">Teams with a correct solution</div>
      <div className="text-6xl font-black tabular-nums">
        {progress.passing} <span className="text-3xl font-bold text-white/70">/ {progress.teams_total}</span>
      </div>
    </div>
  );
}
