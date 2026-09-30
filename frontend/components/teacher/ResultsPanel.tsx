"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { fmtBenchMs, fmtElapsed, fmtPoints } from "@/lib/format";
import { useGame } from "@/lib/store";

// Results for the current question, with the Best Time Complexity override.
export function ResultsPanel({ gameId, onError }: { gameId: string; onError: (m: string | null) => void }) {
  const results = useGame((s) => s.snapshot?.results);
  const [edits, setEdits] = useState<Record<string, { label?: string; points?: string }>>({});
  const [busy, setBusy] = useState(false);
  if (!results) return null;
  const complexity = results.type === "best_complexity";
  const mcq = results.type === "multiple_choice";

  const save = async (teamId: string) => {
    const e = edits[teamId];
    if (!e) return;
    setBusy(true);
    onError(null);
    try {
      await api(`/games/${gameId}/results/override`, {
        body: { team_id: teamId, class_label: e.label ?? null, points: e.points != null && e.points !== "" ? Math.round(Number(e.points)) : null },
      });
      setEdits((x) => {
        const n = { ...x };
        delete n[teamId];
        return n;
      });
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const rescore = async () => {
    setBusy(true);
    onError(null);
    try {
      await api(`/games/${gameId}/questions/${results.question_id}/rescore`, { method: "POST" });
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg bg-ink-800 ring-1 ring-ink-600">
      <div className="flex items-center justify-between border-b border-ink-600 px-3 py-2">
        <h3 className="font-bold text-white">
          Results · {results.round_name}: {results.title}
        </h3>
        <Button size="sm" variant="ghost" onClick={rescore} disabled={busy} title="Recompute automatic points from stored submissions (after a scoring change)">
          Re-score
        </Button>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-ink-400">
          <tr>
            <th className="px-3 py-1.5">Team</th>
            {results.type === "super_fast" && <th>First full pass</th>}
            {results.type === "code_golf" && <th>Chars</th>}
            {mcq && <th>Answer</th>}
            {complexity && (
              <>
                <th>Time at largest n</th>
                <th>Estimated class</th>
              </>
            )}
            <th className="px-3 text-right">Points</th>
            {complexity && <th />}
          </tr>
        </thead>
        <tbody>
          {results.rows.map((r) => {
            const e = edits[r.team_id];
            return (
              <tr key={r.team_id} className="border-t border-ink-700">
                <td className="px-3 py-1.5 text-white">{r.name}</td>
                {results.type === "super_fast" && <td className="font-mono">{r.first_full_ms != null ? fmtElapsed(r.first_full_ms) : r.passed != null ? `${r.passed}/${r.total}` : "–"}</td>}
                {results.type === "code_golf" && <td className="font-mono">{r.chars ?? "–"}</td>}
                {mcq && (
                  <td className={`font-mono ${r.choice == null ? "text-ink-500" : r.correct ? "text-pass" : "text-fail"}`}>
                    {r.choice == null ? "no answer" : `${"ABCD"[r.choice]} ${r.correct ? "✓" : "✗"}${r.answer_ms != null ? ` · ${(r.answer_ms / 1000).toFixed(1)} s` : ""}`}
                  </td>
                )}
                {complexity && (
                  <>
                    <td className="font-mono">{r.time_ms != null ? fmtBenchMs(r.time_ms, results.floor_ms) : r.timed_out ? "timed out" : "–"}</td>
                    <td>
                      {r.class_label != null ? (
                        <input
                          value={e?.label ?? r.class_label ?? ""}
                          onChange={(ev) => setEdits({ ...edits, [r.team_id]: { ...e, label: ev.target.value.slice(0, 40) } })}
                          className="w-48 rounded border border-ink-600 bg-ink-900 px-1.5 py-0.5 text-xs text-white"
                          aria-label={`Class for ${r.name}`}
                        />
                      ) : (
                        <span className="text-ink-500">not passing</span>
                      )}
                    </td>
                  </>
                )}
                <td className="px-3 text-right font-mono text-white">
                  {complexity && r.class_label != null ? (
                    <input
                      type="number"
                      value={e?.points ?? String(r.points)}
                      onChange={(ev) => setEdits({ ...edits, [r.team_id]: { ...e, points: ev.target.value } })}
                      className="w-20 rounded border border-ink-600 bg-ink-900 px-1.5 py-0.5 text-right text-xs text-white"
                      aria-label={`Points for ${r.name}`}
                    />
                  ) : (
                    fmtPoints(r.points)
                  )}
                </td>
                {complexity && (
                  <td className="pr-3 text-right">
                    {e && (
                      <Button size="sm" onClick={() => save(r.team_id)} disabled={busy}>
                        Save
                      </Button>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      {complexity && <p className="px-3 py-2 text-xs text-ink-400">Adjust an estimated class or the points before showing the leaderboard. Estimates can&apos;t separate O(n) from O(n log n).</p>}
    </div>
  );
}
