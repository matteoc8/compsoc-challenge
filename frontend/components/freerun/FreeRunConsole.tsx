"use client";
// Free Run on the host console: pause points (set any time), unlocking the next section,
// hints for any problem, and the live grid.

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { useGame } from "@/lib/store";
import { FreeRunGrid } from "./FreeRunGrid";

export function FreeRunConsole({ gameId, onError }: { gameId: string; onError: (m: string | null) => void }) {
  const snap = useGame((s) => s.snapshot);
  const [busy, setBusy] = useState(false);
  const [hintQ, setHintQ] = useState("");
  const [hintTeam, setHintTeam] = useState("");
  const [finishing, setFinishing] = useState(false);
  const fr = snap?.free_run;
  if (!snap || !fr) return null;
  const state = snap.game.state;
  const finished = ["leaderboard", "podium", "finished"].includes(state);
  const running = state === "open" || state === "paused";

  const call = async (path: string, body: unknown = {}) => {
    setBusy(true);
    onError(null);
    try {
      return await api<{ sent?: number }>(`/games/${gameId}/${path}`, { body });
    } catch (e) {
      onError(e instanceof ApiError ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const toggleBreak = (i: number) => {
    const next = fr.breaks.includes(i) ? fr.breaks.filter((b) => b !== i) : [...fr.breaks, i];
    void call("breaks", { breaks: next });
  };

  const hintQuestion = fr.questions.find((q) => q.id === hintQ);
  const analysis = fr.analysis;
  const mcq = analysis?.results.type === "multiple_choice";
  // teams that have submitted something, best first, to talk through one at a time
  const tried = (analysis?.results.rows ?? []).filter((r) => (r.attempts ?? 0) > 0);
  const current = analysis?.show === "team" ? tried.findIndex((r) => r.team_id === analysis.results.team_solution?.team_id) : -1;
  const show = (what: string, team_id?: string) => void call("analyse/show", { show: what, team_id });
  const finish = async (lock: boolean) => {
    setFinishing(false);
    await call("analyse/end", { lock });
  };
  const sendHint = async (index: number) => {
    const r = await call("hints", { hint_index: index, question_id: hintQ, team_id: hintTeam || null });
    if (r) useGame.getState().toast(r.sent ? `Hint sent to ${r.sent} team${r.sent === 1 ? "" : "s"}` : "Everyone already had that hint", "info");
  };

  return (
    <div className="space-y-5">
      {analysis && (
        <section className="space-y-3 rounded-lg bg-accent/10 p-4 ring-1 ring-accent/50">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="font-bold text-white">Analysing: {analysis.title}</h3>
            <span className="text-xs text-ink-300">(clock paused)</span>
            <Button size="sm" className="ml-auto" disabled={busy} onClick={() => setFinishing(true)}>
              Finish analysis
            </Button>
          </div>
          <div className="flex flex-wrap gap-1">
            {(
              [
                ["results", "Table"],
                ...(mcq ? [] : [["winner", "Best solution"], ["solution", "Model solution"]]),
              ] as [string, string][]
            ).map(([k, label]) => (
              <Button key={k} size="sm" variant={analysis.show === k ? "primary" : "secondary"} disabled={busy} onClick={() => show(k)}>
                {label}
              </Button>
            ))}
          </div>
          {!mcq && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-ink-300">Each team:</span>
              <Button size="sm" variant="secondary" disabled={busy || !tried.length} onClick={() => show("team", tried[(current - 1 + tried.length) % tried.length]?.team_id)}>
                ◀ Previous
              </Button>
              <span className="min-w-[8rem] text-center font-semibold text-white">
                {current >= 0 ? `${tried[current].name} (${current + 1} of ${tried.length})` : tried.length ? `${tried.length} teams submitted` : "No submissions yet"}
              </span>
              <Button size="sm" variant="secondary" disabled={busy || !tried.length} onClick={() => show("team", tried[(current + 1) % tried.length]?.team_id)}>
                Next ▶
              </Button>
            </div>
          )}
        </section>
      )}
      {fr.grid && (state !== "lobby" || fr.grid.length > 0) && (
        <section className="rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-bold text-white">Teams</h3>
            {!!fr.in_flight && <span className="animate-pulse text-xs text-ink-300">{fr.in_flight} being judged</span>}
          </div>
          <FreeRunGrid fr={fr} />
        </section>
      )}

      {!finished && (
        <section className="rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
          <div className="mb-2 flex flex-wrap items-center gap-3">
            <h3 className="font-bold text-white">Problems</h3>
            <span className="text-xs text-ink-400">
              {fr.visible < fr.total ? `${fr.visible} of ${fr.total} open` : "All open"}
            </span>
            {fr.visible < fr.total && (
              <Button size="sm" className="ml-auto" disabled={busy} onClick={() => void call("unlock-next")}>
                Unlock next section
              </Button>
            )}
          </div>
          <ol className="text-sm">
            {fr.questions.map((q, i) => (
              <li key={q.id}>
                <div className={`flex items-center gap-2 py-1 ${q.locked ? "text-ink-400" : "text-white"}`}>
                  <span className="w-5 tabular-nums text-ink-400">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate">
                    {q.title} <span className="text-xs text-ink-400">({q.type_label})</span>
                  </span>
                  {q.locked && <span className="text-xs text-ink-400">locked</span>}
                  {q.closed && <span className="text-xs text-ink-400">closed</span>}
                  {running && !analysis && !q.locked && (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => void call("analyse", { question_id: q.id })}>
                      Analyse
                    </Button>
                  )}
                </div>
                {i < fr.questions.length - 1 && (
                  <button
                    onClick={() => toggleBreak(i)}
                    disabled={busy}
                    className={`my-0.5 w-full rounded border border-dashed px-2 py-0.5 text-left text-[11px] font-semibold ${
                      fr.breaks.includes(i) ? "border-accent bg-accent/15 text-accent" : "border-transparent text-ink-500 hover:border-ink-500 hover:text-ink-300"
                    }`}
                    title="Teams can't go past a pause point until you unlock the next section"
                  >
                    {fr.breaks.includes(i) ? "Pause point (click to remove)" : "+ pause point"}
                  </button>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {running && (
        <section className="space-y-2 rounded-lg bg-ink-800 p-4 text-sm ring-1 ring-ink-600">
          <h3 className="font-bold text-white">Hints</h3>
          <div className="flex flex-wrap gap-2">
            <select value={hintQ} onChange={(e) => setHintQ(e.target.value)} className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-white" aria-label="Problem">
              <option value="">Problem…</option>
              {fr.questions
                .filter((q) => q.hints?.length)
                .map((q) => (
                  <option key={q.id} value={q.id}>
                    {q.index + 1}. {q.title}
                  </option>
                ))}
            </select>
            <select value={hintTeam} onChange={(e) => setHintTeam(e.target.value)} className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-white" aria-label="Team">
              <option value="">Every team</option>
              {(fr.grid ?? []).map((t) => (
                <option key={t.team_id} value={t.team_id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
          {hintQuestion?.hints?.map((h, i) => (
            <button key={i} disabled={busy} onClick={() => void sendHint(i)} className="block w-full rounded bg-ink-700 px-2 py-1.5 text-left text-xs text-white hover:bg-ink-600">
              <b>Hint {i + 1}:</b> {h}
            </button>
          ))}
          {!fr.questions.some((q) => q.hints?.length) && <p className="text-xs text-ink-400">No problems in this quiz have hints.</p>}
        </section>
      )}
      <Modal open={finishing} title="Lock this problem?" onClose={() => setFinishing(false)} onConfirm={() => void finish(true)} confirmLabel="Lock it" busy={busy}>
        Locking stops any more submissions or answers on {analysis?.title ? `"${analysis.title}"` : "this problem"}. Points so far stay. If the clock was running before, it restarts.
        <div className="mt-4">
          <Button variant="secondary" disabled={busy} onClick={() => void finish(false)}>
            Keep it open
          </Button>
        </div>
      </Modal>
    </div>
  );
}
