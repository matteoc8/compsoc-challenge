"use client";
// Teacher console: a separate device, not projected.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Analytics } from "@/components/teacher/Analytics";
import { Controls } from "@/components/teacher/Controls";
import { PointsPanel } from "@/components/teacher/PointsPanel";
import { ResultsPanel } from "@/components/teacher/ResultsPanel";
import { SubmissionMonitor } from "@/components/teacher/SubmissionMonitor";
import { ConnectionBadge } from "@/components/ui/ConnectionBadge";
import { api } from "@/lib/api";
import { useGameSocket } from "@/lib/socket";
import { useGame } from "@/lib/store";
import { useTeacher } from "@/lib/teacher";

const STATE_LABEL: Record<string, string> = {
  lobby: "Lobby",
  round_intro: "Round intro",
  open: "Question open",
  paused: "Paused",
  closed: "Time's up",
  judging: "Measuring speed",
  results: "Results",
  leaderboard: "Leaderboard",
  podium: "Podium",
  finished: "Finished",
};

export default function ConsolePage() {
  const me = useTeacher();
  const { id } = useParams<{ id: string }>();
  const params = useMemo(() => (me && id ? { role: "teacher", game: id } : null), [me, id]);
  useGameSocket(params);
  const snap = useGame((s) => s.snapshot);
  const status = useGame((s) => s.status);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"points" | "stats">("points");

  if (!me) return null;
  if (status === "unauthorised") return <main className="p-6 text-fail">You can&apos;t open this game. Is it yours, and are you logged in?</main>;
  if (!snap || snap.role !== "teacher") return <main className="p-6 text-ink-400">Connecting…</main>;

  const g = snap.game;
  const projectorUrl = `/presentation?game=${g.id}&token=${encodeURIComponent(snap.screen_token ?? "")}`;
  const inQuestion = ["open", "paused", "closed", "judging"].includes(g.state);
  const settings = snap.settings ?? {};

  const toggle = (key: "allow_negative_totals" | "show_reasons" | "sounds", value: boolean) =>
    api(`/games/${g.id}/settings`, { body: { [key]: value } }).catch(() => setError("Couldn't save the setting"));

  return (
    <main className="min-h-full">
      <header className="flex flex-wrap items-center gap-4 border-b border-ink-600 bg-ink-800 px-5 py-3">
        <Link href="/teacher" className="text-sm text-ink-400 hover:text-white">
          ← Teacher home
        </Link>
        <div className="flex items-baseline gap-2">
          <span className="text-xs text-ink-400">Code</span>
          <span className="font-mono text-2xl font-black tracking-widest text-white">{g.join_code}</span>
        </div>
        <span className="rounded bg-round-blue/20 px-2 py-1 text-sm font-bold text-white">{STATE_LABEL[g.state]}</span>
        {g.question_index >= 0 && (
          <span className="text-sm text-ink-300">
            Round {g.question_index + 1} of {g.question_count}
            {g.round_name ? ` · ${g.round_name}` : ""}
          </span>
        )}
        <a href={projectorUrl} target="_blank" rel="noopener" className="ml-auto rounded-md bg-accent px-3 py-1.5 text-sm font-bold text-black hover:bg-accent-light">
          Open projector ↗
        </a>
      </header>
      {!g.judge_ok && (
        <div className="bg-fail px-5 py-2 text-sm font-bold text-white" role="alert">
          The judge (Judge0) isn&apos;t responding. Submissions are retrying; consider pausing or adding time.
        </div>
      )}
      {error && (
        <div className="flex items-center justify-between bg-fail/15 px-5 py-2 text-sm text-fail" role="alert">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
      <div className="grid gap-5 p-5 xl:grid-cols-[1fr_540px]">
        <div className="min-w-0 space-y-5">
          <section className="rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
            <Controls gameId={g.id} onError={setError} />
          </section>
          {g.state === "lobby" && (
            <section className="rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
              <h3 className="mb-2 font-bold text-white">Teams ({snap.teams?.length ?? 0})</h3>
              <ul className="space-y-1 text-sm">
                {(snap.teams ?? []).map((t) => (
                  <li key={t.team_id} className="flex items-center gap-2">
                    <span className={`inline-block h-2 w-2 rounded-full ${t.online ? "bg-pass" : "bg-ink-500"}`} />
                    <span className="text-white">{t.name}</span>
                  </li>
                ))}
                {!snap.teams?.length && <li className="text-ink-400">Waiting for teams. Open the projector so they can see the code.</li>}
              </ul>
            </section>
          )}
          {inQuestion && <SubmissionMonitor />}
          {(g.state === "results" || g.state === "leaderboard") && <ResultsPanel gameId={g.id} onError={setError} />}
          {(g.state === "podium" || g.state === "finished") && <Analytics gameId={g.id} refreshKey={g.state} />}
          <section className="rounded-lg bg-ink-800 p-4 text-sm ring-1 ring-ink-600">
            <h3 className="mb-2 font-bold text-white">Questions</h3>
            <ol className="space-y-1">
              {(snap.questions ?? []).map((q, i) => (
                <li key={q.id} className={i === g.question_index ? "font-bold text-white" : "text-ink-300"}>
                  {i + 1}. {q.round_name}: {q.title}
                </li>
              ))}
            </ol>
          </section>
        </div>
        <aside className="space-y-4">
          <div className="flex gap-1 rounded-md bg-ink-800 p-1 ring-1 ring-ink-600">
            {(["points", "stats"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`flex-1 rounded px-3 py-1.5 text-sm font-semibold ${tab === t ? "bg-ink-600 text-white" : "text-ink-400"}`}>
                {t === "points" ? "Points & teams" : "Stats & export"}
              </button>
            ))}
          </div>
          {tab === "points" ? <PointsPanel gameId={g.id} onError={setError} /> : <Analytics gameId={g.id} refreshKey={`${g.state}-${g.question_index}`} />}
          <section className="space-y-2 rounded-lg bg-ink-800 p-4 text-sm ring-1 ring-ink-600">
            <h3 className="font-bold text-white">Settings</h3>
            {(
              [
                ["show_reasons", "Show point reasons on the projector", settings.show_reasons !== false],
                ["allow_negative_totals", "Allow totals below zero", !!settings.allow_negative_totals],
                ["sounds", "Projector sounds", settings.sounds !== false],
              ] as const
            ).map(([k, label, v]) => (
              <label key={k} className="flex items-center gap-2 text-ink-200">
                <input type="checkbox" checked={v} onChange={(e) => toggle(k, e.target.checked)} />
                {label}
              </label>
            ))}
          </section>
        </aside>
      </div>
      <ConnectionBadge />
    </main>
  );
}
