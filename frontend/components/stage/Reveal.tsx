"use client";
// After a coding question: the winning team's solution and the model solution, shown on the
// projector when the host spotlights them, and on every team's results screen once revealed.

import { fmtPoints } from "@/lib/format";
import type { QType, Results, Winner } from "@/lib/types";

function detail(w: Winner, type: QType): string {
  const parts = [`${w.passed ?? 0}/${w.total ?? 0} tests`];
  if (type === "code_golf") parts.push(`${w.chars} chars`);
  if (w.class_label) parts.push(w.class_label);
  return parts.join(" · ");
}

function Code({ code, compact }: { code: string; compact?: boolean }) {
  return (
    <pre
      className={`overflow-auto rounded-xl bg-black/40 font-mono text-white ring-1 ring-white/15 ${compact ? "max-h-80 p-4 text-sm" : "max-h-[62vh] p-6 text-2xl leading-snug"}`}
    >
      {code}
    </pre>
  );
}

export function WinnerSpotlight({ winner, type, compact, label = "Winning solution" }: { winner: Winner; type: QType; compact?: boolean; label?: string }) {
  return (
    <div className={compact ? "space-y-3" : "flex h-full flex-col gap-6 p-10"}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className={`font-stage font-extrabold uppercase tracking-widest text-accent ${compact ? "text-sm" : "text-2xl"}`}>{label}</div>
          <div className={`font-stage font-black text-white ${compact ? "text-3xl" : "text-7xl"}`}>{winner.name}</div>
          <div className={`font-stage font-bold text-white/75 ${compact ? "text-base" : "text-2xl"}`}>{detail(winner, type)}</div>
        </div>
        <div className={`rounded-xl bg-white font-stage font-black text-stage-deep ${compact ? "px-4 py-2 text-2xl" : "px-8 py-4 text-6xl"}`}>
          {fmtPoints(winner.points)} <span className={compact ? "text-base" : "text-2xl"}>pts</span>
        </div>
      </div>
      <Code code={winner.code} compact={compact} />
    </div>
  );
}

export function SolutionSpotlight({ code, compact }: { code: string; compact?: boolean }) {
  return (
    <div className={compact ? "space-y-3" : "flex h-full flex-col gap-6 p-10"}>
      <div className={`font-stage font-black text-white ${compact ? "text-2xl" : "text-6xl"}`}>Model solution</div>
      <Code code={code} compact={compact} />
    </div>
  );
}

/** Team results screen: whatever has been revealed so far, under their own score. */
export function TeamReveals({ results }: { results: Results }) {
  if (!results.winner && !results.model_solution) return null;
  return (
    <div className="mx-6 mt-6 space-y-6 rounded-xl bg-black/20 p-5">
      {results.winner && <WinnerSpotlight winner={results.winner} type={results.type} compact />}
      {results.model_solution && <SolutionSpotlight code={results.model_solution} compact />}
    </div>
  );
}
