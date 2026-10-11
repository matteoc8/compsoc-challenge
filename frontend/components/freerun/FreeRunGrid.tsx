"use client";
// Free Run on the projector and the host console: every team against every problem, live.

import { Rank } from "@/components/ui/Rank";
import { fmtPoints } from "@/lib/format";
import type { FreeRun, FreeRunCell } from "@/lib/types";

const CELL: Record<string, string> = {
  solved: "bg-pass/80 text-white",
  correct: "bg-pass/80 text-white",
  partial: "bg-round-yellow/80 text-black",
  wrong: "bg-fail/70 text-white",
  tried: "bg-white/10 text-white/60",
  judging: "animate-pulse bg-white/20 text-white",
};

function Cell({ cell, stage }: { cell?: FreeRunCell; stage: boolean }) {
  if (!cell?.status) return <span className="text-white/20">·</span>;
  const label =
    cell.status === "judging" ? "…" : cell.points ? fmtPoints(cell.points) : cell.status === "wrong" ? "✗" : cell.status === "tried" ? "0" : "✓";
  return (
    <span className={`inline-flex min-w-[3.2em] justify-center rounded px-1.5 py-0.5 font-bold tabular-nums ${stage ? "text-lg" : "text-xs"} ${CELL[cell.status]}`}>
      {label}
    </span>
  );
}

export function FreeRunGrid({ fr, stage = false, limit }: { fr: FreeRun; stage?: boolean; limit?: number }) {
  const rows = (fr.grid ?? []).slice(0, limit);
  const breaks = new Set(fr.breaks);
  return (
    <div className={`overflow-x-auto rounded-xl ${stage ? "bg-black/25 p-4" : "bg-ink-900 p-2 ring-1 ring-ink-600"}`}>
      <table className={`w-full ${stage ? "font-stage text-xl" : "text-sm"}`}>
        <thead>
          <tr className={`text-left ${stage ? "text-base uppercase tracking-wide text-white/60" : "text-xs text-ink-400"}`}>
            <th className="w-10 px-2 py-1.5">#</th>
            <th className="px-2">Team</th>
            {fr.questions.map((q) => (
              <th
                key={q.id}
                className={`px-1.5 text-center ${q.locked ? "opacity-40" : ""} ${breaks.has(q.index - 1) ? "border-l-2 border-accent/60" : ""}`}
                title={q.title ?? "Locked"}
              >
                {q.index + 1}
              </th>
            ))}
            <th className="px-2 text-right">Points</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.team_id} className={stage ? "border-t border-white/10" : "border-t border-ink-700"}>
              <td className="px-2 py-1.5">
                <Rank rank={r.rank} />
              </td>
              <td className={`max-w-[14rem] truncate px-2 font-bold ${stage ? "text-white" : "text-white"}`}>{r.name}</td>
              {fr.questions.map((q) => (
                <td key={q.id} className={`px-1.5 text-center ${q.locked ? "opacity-40" : ""} ${breaks.has(q.index - 1) ? "border-l-2 border-accent/60" : ""}`}>
                  <Cell cell={r.cells[q.id]} stage={stage} />
                </td>
              ))}
              <td className={`px-2 text-right font-black tabular-nums ${stage ? "text-accent" : "text-white"}`}>{fmtPoints(r.points)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={fr.questions.length + 3} className="px-2 py-3 text-white/50">
                No teams yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
