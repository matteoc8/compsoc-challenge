"use client";
// Free Run on a team's computer: the problem list down the side, the chosen problem on the
// right. Problems past the host's pause point stay locked until the host unlocks them.

import { useEffect, useState } from "react";
import { AnswerTiles, Shape, TILE } from "@/components/mcq/AnswerTiles";
import { FreeRunAnalysis } from "./FreeRunAnalysis";
import { MeasuringSpeed } from "@/components/stage/Results";
import { Markdown } from "@/components/ui/Markdown";
import { Workspace } from "@/components/workspace/Workspace";
import { api, ApiError } from "@/lib/api";
import { fmtPoints } from "@/lib/format";
import { useGame } from "@/lib/store";
import type { FreeRunCell, Hint, PublicQuestion } from "@/lib/types";

const STATUS_STYLE: Record<string, string> = {
  solved: "bg-pass text-white",
  correct: "bg-pass text-white",
  partial: "bg-round-yellow text-black",
  wrong: "bg-fail text-white",
  tried: "bg-ink-500 text-white",
  judging: "animate-pulse bg-ink-500 text-white",
};

function StatusBadge({ cell }: { cell?: FreeRunCell }) {
  if (!cell?.status) return null;
  const text = cell.status === "judging" ? "judging" : cell.points ? `${fmtPoints(cell.points)}` : cell.status === "wrong" ? "wrong" : cell.status === "correct" ? "✓" : "0";
  return <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-bold tabular-nums ${STATUS_STYLE[cell.status]}`}>{text}</span>;
}

export function FreeRunPlay({ token }: { token: string }) {
  const snap = useGame((s) => s.snapshot);
  const fr = snap?.free_run;
  const problems = fr?.problems ?? [];
  const [selected, setSelected] = useState<string | null>(null);

  // Start on the first problem not yet solved; stay put after that.
  useEffect(() => {
    if (selected && problems.some((p) => p.id === selected)) return;
    const open = problems.find((p) => !["solved", "correct"].includes(fr?.status?.[p.id]?.status ?? ""));
    setSelected((open ?? problems[0])?.id ?? null);
  }, [problems, fr?.status, selected]);

  if (!snap || !fr) return null;
  const state = snap.game.state;
  const ended = state === "closed" || state === "judging";
  const q = problems.find((p) => p.id === selected);
  const closed = !!fr.questions.find((p) => p.id === q?.id)?.closed;
  const locked = ended || closed;
  const hints = (q && fr.hints?.[q.id]) || [];

  return (
    <div className="flex h-full">
      <nav className="flex w-60 shrink-0 flex-col overflow-y-auto border-r border-ink-600 bg-ink-800" aria-label="Problems">
        {fr.questions.map((p) => {
          const active = p.id === selected;
          const breakAfter = fr.breaks.includes(p.index);
          return (
            <div key={p.id}>
              <button
                disabled={p.locked}
                onClick={() => setSelected(p.id)}
                aria-current={active ? "true" : undefined}
                className={`flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm ${active ? "bg-ink-600 text-white" : "text-ink-200 hover:bg-ink-700"} disabled:cursor-not-allowed disabled:opacity-40`}
              >
                <span className="w-5 shrink-0 font-bold tabular-nums text-ink-400">{p.index + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{p.locked ? "Locked" : p.title}</span>
                  <span className="block truncate text-[11px] text-ink-400">{p.type_label}</span>
                </span>
                {p.closed && <span className="shrink-0 rounded bg-ink-600 px-1.5 py-0.5 text-[10px] font-bold uppercase text-ink-300">Closed</span>}
                {!p.locked && <StatusBadge cell={fr.status?.[p.id]} />}
              </button>
              {breakAfter && (
                <div className={`border-y border-accent/30 bg-accent/10 px-3 py-1 text-[11px] font-bold uppercase tracking-wide ${p.index + 1 < fr.visible ? "text-accent/60" : "text-accent"}`}>
                  {p.index + 1 < fr.visible ? "Unlocked" : "Waiting for the host"}
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <section className="relative flex min-w-0 flex-1 flex-col">
        {hints.length > 0 && <ProblemHints hints={hints} />}
        <div className="min-h-0 flex-1">
          {q && q.type === "multiple_choice" && <FreeRunMcq key={q.id} q={q} token={token} locked={locked} />}
          {q && q.type !== "multiple_choice" && (
            <Workspace
              key={q.id}
              question={q}
              token={token}
              scope={snap.game.id}
              locked={locked}
              lockedMessage={closed && !ended ? "Closed after it was analysed" : state === "judging" ? "Time's up! Measuring speed…" : "Time's up!"}
              submissions={fr.submissions?.[q.id] ?? []}
              questionPoints={fr.status?.[q.id]?.points}
            />
          )}
        </div>
        {state === "judging" && (
          <div className="stage-bg absolute inset-0 z-20 opacity-95">
            <MeasuringSpeed />
          </div>
        )}
        {fr.analysis && !ended && (
          <div className="stage-bg absolute inset-0 z-30 overflow-y-auto">
            <FreeRunAnalysis analysis={fr.analysis} compact myTeamId={snap.me?.team_id} />
          </div>
        )}
      </section>
    </div>
  );
}

function ProblemHints({ hints }: { hints: Hint[] }) {
  return (
    <div className="space-y-0.5 border-b border-round-yellow/40 bg-round-yellow/15 px-4 py-1.5 text-sm text-white" role="status">
      {hints.map((h) => (
        <div key={h.index}>
          <b className="text-round-yellow">Hint {h.number}:</b> {h.text}
        </div>
      ))}
    </div>
  );
}

function FreeRunMcq({ q, token, locked }: { q: PublicQuestion; token: string; locked: boolean }) {
  const snap = useGame((s) => s.snapshot);
  const toast = useGame((s) => s.toast);
  const [sending, setSending] = useState<number | null>(null);
  const answered = snap?.free_run?.answers?.[q.id];
  const cell = snap?.free_run?.status?.[q.id];
  const paused = snap?.game.paused;

  const pick = async (i: number) => {
    if (answered != null || sending != null || locked || paused) return;
    setSending(i);
    try {
      await api("/answers", { body: { question_id: q.id, choice: i }, token });
      const cur = useGame.getState().snapshot;
      if (cur?.free_run) useGame.setState({ snapshot: { ...cur, free_run: { ...cur.free_run, answers: { ...cur.free_run.answers, [q.id]: i } } } });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't send your answer", "bad");
    } finally {
      setSending(null);
    }
  };

  const chosen = answered ?? sending;
  return (
    <div className="stage-bg flex h-full flex-col gap-4 overflow-y-auto p-6">
      <h1 className="font-stage text-3xl font-black leading-tight text-white">{q.title}</h1>
      {q.description_md && <Markdown className="text-white/90">{q.description_md}</Markdown>}
      {q.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={q.image_url} alt={q.image_alt || ""} className="mx-auto max-h-[28vh] rounded-lg object-contain shadow-xl" />
      )}
      {chosen != null ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
          <div className="flex items-center gap-4 rounded-xl px-8 py-6 font-stage text-3xl font-black text-white shadow-xl" style={{ background: TILE[chosen % 4].color }}>
            <Shape i={chosen} size={40} />
            {q.options?.[chosen]?.text}
          </div>
          <p className="font-stage text-2xl font-black text-white">
            {sending != null ? "Sending…" : cell?.status === "correct" ? `Correct! +${fmtPoints(cell.points)}` : cell?.status === "wrong" ? "Not quite" : "Answer locked in"}
          </p>
        </div>
      ) : locked ? (
        <p className="py-10 text-center font-stage text-4xl font-black text-white">{snap?.game.state === "open" || snap?.game.paused ? "Closed after it was analysed" : "Time's up!"}</p>
      ) : (
        <div className="min-h-[40vh] flex-1">
          <AnswerTiles options={q.options ?? []} onPick={pick} disabled={!!paused} />
        </div>
      )}
      {paused && chosen == null && <p className="text-center font-stage text-xl font-black text-round-yellow">Paused: answers open again when the game resumes</p>}
    </div>
  );
}
