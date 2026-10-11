"use client";
// Free Run analyse mode: the clock is paused and every screen looks at one problem: how the
// teams did, the best team solution so far, or the model solution.

import { McqResults } from "@/components/mcq/McqViews";
import { ResultsView } from "@/components/stage/Results";
import { SolutionSpotlight, WinnerSpotlight } from "@/components/stage/Reveal";
import type { FreeRun } from "@/lib/types";

export function FreeRunAnalysis({ analysis, compact = false, myTeamId }: { analysis: NonNullable<FreeRun["analysis"]>; compact?: boolean; myTeamId?: string }) {
  const r = analysis.results;
  return (
    <div className={`flex h-full flex-col ${compact ? "gap-4 p-6" : "gap-2 pt-8"}`}>
      <div className={compact ? "" : "px-10"}>
        <div className={`font-stage font-extrabold uppercase tracking-widest text-accent ${compact ? "text-sm" : "text-2xl"}`}>Analysing (clock paused)</div>
        <h1 className={`font-stage font-black text-white ${compact ? "text-3xl" : "text-6xl"}`}>{analysis.title}</h1>
      </div>
      <div className="min-h-0 flex-1">
        {analysis.show === "team" && r.team_solution ? (
          <WinnerSpotlight winner={r.team_solution} type={r.type} compact={compact} label="Team solution" />
        ) : analysis.show === "winner" && r.winner ? (
          <WinnerSpotlight winner={r.winner} type={r.type} compact={compact} label="Best solution so far" />
        ) : analysis.show === "solution" && r.model_solution != null ? (
          <SolutionSpotlight code={r.model_solution} compact={compact} />
        ) : r.type === "multiple_choice" ? (
          <McqResults results={r} compact={compact} myTeamId={myTeamId} />
        ) : (
          <ResultsView results={r} compact={compact} myTeamId={myTeamId} />
        )}
      </div>
    </div>
  );
}
