"use client";
import { useState } from "react";
import { InlineCountdown, RingCountdown } from "@/components/stage/Countdown";
import { api, ApiError } from "@/lib/api";
import { fmtPoints, ordinal } from "@/lib/format";
import { useGame } from "@/lib/store";
import type { PublicQuestion, Results } from "@/lib/types";
import { AnswerBars, AnswerTiles, Shape, TILE } from "./AnswerTiles";

/** Team computer: the question and four answer buttons. One answer, locked in. */
export function McqPlay({ q, token }: { q: PublicQuestion; token: string }) {
  const snap = useGame((s) => s.snapshot);
  const toast = useGame((s) => s.toast);
  const [sending, setSending] = useState<number | null>(null);
  const mine = snap?.my_answer?.choice ?? null;
  const state = snap?.game.state;
  const closed = state === "closed";
  const paused = snap?.game.paused;
  const progress = snap?.progress;

  const pick = async (i: number) => {
    if (mine != null || sending != null || closed || paused) return;
    setSending(i);
    try {
      await api("/answers", { body: { question_id: q.id, choice: i }, token });
      const cur = useGame.getState().snapshot;
      if (cur) useGame.setState({ snapshot: { ...cur, my_answer: { choice: i } } });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't send your answer", "bad");
    } finally {
      setSending(null);
    }
  };

  const chosen = mine ?? sending;
  return (
    <div className="stage-bg flex h-full flex-col gap-4 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="font-stage text-sm font-extrabold uppercase tracking-widest text-accent">{q.round_name}</div>
          <h1 className="font-stage text-3xl font-black leading-tight text-white">{q.title}</h1>
        </div>
        <div className="flex flex-col items-end gap-1">
          <InlineCountdown className="text-3xl" />
          {progress?.answered != null && (
            <span className="text-sm font-bold text-white/70">
              {progress.answered} / {progress.teams_total} answered
            </span>
          )}
        </div>
      </div>
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
          <p className="font-stage text-2xl font-black text-white">{sending != null ? "Sending…" : "Answer locked in"}</p>
          <p className="font-stage text-lg font-bold text-white/70">{closed ? "Time's up! Results coming…" : "Waiting for the other teams…"}</p>
        </div>
      ) : closed ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="font-stage text-5xl font-black text-white">Time&apos;s up!</p>
        </div>
      ) : (
        <div className="min-h-0 flex-1">
          <AnswerTiles options={q.options ?? []} onPick={pick} disabled={!!paused} />
        </div>
      )}
      {paused && chosen == null && <p className="text-center font-stage text-xl font-black text-round-yellow">Paused: answers open again when the game resumes</p>}
    </div>
  );
}

/** Projector while the question is open. */
export function McqStage({ q, sound }: { q: PublicQuestion; sound: boolean }) {
  const progress = useGame((s) => s.snapshot?.progress);
  return (
    <div className="flex h-full flex-col gap-6 p-10">
      <div className="flex items-start gap-8">
        <div className="min-w-0 flex-1">
          <div className="font-stage text-2xl font-extrabold uppercase tracking-widest text-accent">{q.round_name}</div>
          <h1 className="mt-2 font-stage text-6xl font-black leading-tight text-white">{q.title}</h1>
        </div>
        <div className="flex shrink-0 flex-col items-center gap-3">
          <RingCountdown size={220} sound={sound} />
          <div className="font-stage text-2xl font-black text-white">
            {progress?.answered ?? 0} <span className="text-white/70">/ {progress?.teams_total ?? 0} answered</span>
          </div>
        </div>
      </div>
      {q.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={q.image_url} alt={q.image_alt || ""} className="mx-auto max-h-[34vh] rounded-xl object-contain shadow-2xl" />
      )}
      <div className="mt-auto">
        <AnswerTiles options={q.options ?? []} size="lg" />
      </div>
    </div>
  );
}

/** Results for a multiple-choice question: bars per answer, then who got it. */
export function McqResults({ results, compact = false, myTeamId }: { results: Results; compact?: boolean; myTeamId?: string }) {
  const options = results.options ?? [];
  const right = results.rows.filter((r) => r.correct);
  return (
    <div className={`flex h-full flex-col ${compact ? "gap-4 p-5" : "gap-8 p-10"}`}>
      <div>
        <div className="font-stage text-xl font-bold uppercase tracking-widest text-accent">{results.round_name}</div>
        <h1 className={`font-stage font-black text-white ${compact ? "text-2xl" : "text-5xl"}`}>{results.title}</h1>
      </div>
      <AnswerBars options={options} compact={compact} />
      <AnswerTiles options={options} size={compact ? "md" : "lg"} reveal={{ correct: options.map((o) => o.correct) }} />
      {!compact && (
        <p className="text-center font-stage text-2xl font-bold text-white/80">
          {right.length
            ? `${right.length} of ${results.rows.length} teams got it · fastest: ${right[0].name} (+${fmtPoints(right[0].points)})`
            : "Nobody got this one!"}
        </p>
      )}
      {compact && myTeamId && <McqMine results={results} myTeamId={myTeamId} />}
    </div>
  );
}

function McqMine({ results, myTeamId }: { results: Results; myTeamId: string }) {
  const row = results.rows.find((r) => r.team_id === myTeamId);
  if (!row) return null;
  const pos = results.rows.filter((r) => r.correct).findIndex((r) => r.team_id === myTeamId);
  return (
    <div className={`rounded-xl p-5 text-center font-stage shadow-xl ${row.correct ? "bg-pass text-white" : "bg-fail text-white"}`}>
      <div className="text-4xl font-black">{row.correct ? `Correct! +${fmtPoints(row.points)}` : row.choice == null ? "No answer" : "Not this time"}</div>
      {row.correct && pos >= 0 && (
        <div className="text-lg font-bold text-white/85">{pos === 0 ? "Fastest correct answer!" : `${ordinal(pos + 1)} fastest correct answer`}</div>
      )}
    </div>
  );
}
