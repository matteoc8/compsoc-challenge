"use client";
import { fmtElapsed, fmtPoints } from "@/lib/format";
import { EMPTY_LIST, useGame } from "@/lib/store";

const LETTERS = "ABCD";

export function SubmissionMonitor() {
  const rows = useGame((s) => s.snapshot?.monitor ?? EMPTY_LIST);
  const q = useGame((s) => s.snapshot?.question);
  if (q?.type === "multiple_choice") return <AnswerMonitor />;
  const golf = q?.type === "code_golf";
  const visible = rows.filter((r) => !r.kicked);
  return (
    <div className="overflow-x-auto rounded-lg bg-ink-800 ring-1 ring-ink-600">
      <table className="w-full text-sm">
        <thead className="bg-ink-700 text-left text-xs text-ink-300">
          <tr>
            <th className="px-3 py-2">Team</th>
            <th className="px-2">Attempts</th>
            <th className="px-2">Runs</th>
            <th className="px-2">Best pass rate</th>
            {golf && <th className="px-2">Chars</th>}
            <th className="px-2">First full pass</th>
            <th className="px-3 text-right">Points{q?.type !== "super_fast" ? " (provisional)" : ""}</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => (
            <tr key={r.team_id} className="border-t border-ink-700">
              <td className="px-3 py-1.5">
                <span className={`mr-2 inline-block h-2 w-2 rounded-full ${r.online ? "bg-pass" : "bg-ink-500"}`} title={r.online ? "online" : "offline"} />
                <span className="text-white">{r.name}</span>
                {r.in_flight && <span className="ml-2 animate-pulse text-xs text-round-yellow">judging</span>}
              </td>
              <td className="px-2 font-mono">{r.attempts}</td>
              <td className="px-2 font-mono">{r.runs}</td>
              <td className="px-2">
                {r.best_pass_rate == null ? (
                  <span className="text-ink-500">–</span>
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-20 overflow-hidden rounded bg-ink-600">
                      <div className={`h-full ${r.best_pass_rate === 1 ? "bg-pass" : "bg-round-yellow"}`} style={{ width: `${Math.round(r.best_pass_rate * 100)}%` }} />
                    </div>
                    <span className="font-mono text-xs">{Math.round(r.best_pass_rate * 100)}%</span>
                  </div>
                )}
              </td>
              {golf && <td className="px-2 font-mono">{r.best_chars ?? "–"}</td>}
              <td className="px-2 font-mono">{r.first_full_ms != null ? fmtElapsed(r.first_full_ms) : "–"}</td>
              <td className="px-3 text-right font-mono text-white">
                {r.provisional_points != null ? fmtPoints(r.provisional_points) : r.passing && q?.type === "best_complexity" ? "passing" : "–"}
              </td>
            </tr>
          ))}
          {!visible.length && (
            <tr>
              <td colSpan={7} className="px-3 py-3 text-ink-400">
                No teams.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Multiple choice: who has answered, what, and whether it's right (console only). */
function AnswerMonitor() {
  const rows = useGame((s) => s.snapshot?.monitor ?? EMPTY_LIST).filter((r) => !r.kicked);
  const q = useGame((s) => s.snapshot?.question);
  const correct = new Set(q?.correct ?? []);
  return (
    <div className="overflow-x-auto rounded-lg bg-ink-800 ring-1 ring-ink-600">
      <div className="border-b border-ink-600 px-3 py-2 text-sm text-ink-300">
        Correct answer:{" "}
        <b className="text-pass">
          {(q?.options ?? [])
            .filter((o) => correct.has(o.index))
            .map((o) => `${LETTERS[o.index]}. ${o.text}`)
            .join(" / ")}
        </b>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-ink-700 text-left text-xs text-ink-300">
          <tr>
            <th className="px-3 py-2">Team</th>
            <th className="px-2">Answer</th>
            <th className="px-2">Time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.team_id} className="border-t border-ink-700">
              <td className="px-3 py-1.5">
                <span className={`mr-2 inline-block h-2 w-2 rounded-full ${r.online ? "bg-pass" : "bg-ink-500"}`} />
                <span className="text-white">{r.name}</span>
              </td>
              <td className={`px-2 font-mono ${r.answered ? (r.correct ? "text-pass" : "text-fail") : "text-ink-500"}`}>
                {r.answered && r.choice != null ? `${LETTERS[r.choice]} ${r.correct ? "✓" : "✗"}` : "waiting…"}
              </td>
              <td className="px-2 font-mono">{r.answer_ms != null ? `${(r.answer_ms / 1000).toFixed(1)} s` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
