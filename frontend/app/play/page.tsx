"use client";
// Team computer: lobby (with a practice problem), round intro, workspace, results, leaderboard, podium.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Leaderboard } from "@/components/leaderboard/Leaderboard";
import { McqPlay, McqResults } from "@/components/mcq/McqViews";
import { Podium } from "@/components/leaderboard/Podium";
import { MeasuringSpeed, ResultsView } from "@/components/stage/Results";
import { RoundIntro } from "@/components/stage/RoundIntro";
import { ConnectionBadge } from "@/components/ui/ConnectionBadge";
import { Toasts } from "@/components/ui/Toasts";
import { Workspace } from "@/components/workspace/Workspace";
import { api, getTeamToken, setTeamToken } from "@/lib/api";
import { BRAND } from "@/lib/brand";
import { fmtPoints, ordinal } from "@/lib/format";
import { useGameSocket } from "@/lib/socket";
import { useGame } from "@/lib/store";

interface Practice {
  id: string;
  round_name: string;
  title: string;
  description_md: string;
  starter_code: string;
  examples: { stdin: string; expected: string }[];
}

export default function PlayPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const t = getTeamToken();
    if (!t) router.replace("/join");
    else setToken(t);
  }, [router]);

  const params = useMemo(() => (token ? { role: "team", token } : null), [token]);
  useGameSocket(params, generation);
  const status = useGame((s) => s.status);
  const statusMessage = useGame((s) => s.statusMessage);
  const snap = useGame((s) => s.snapshot);

  if (!token) return null;

  if (status === "unauthorised" || status === "ended") {
    return (
      <Center>
        <h1 className="font-stage text-4xl font-black text-white">{status === "ended" ? "You've left the game" : "That team isn't in a game any more"}</h1>
        <p className="mt-3 font-stage text-lg font-bold text-white/80">{statusMessage ?? "Join again with the game code."}</p>
        <Link
          href="/join"
          onClick={() => setTeamToken(null)}
          className="mt-6 inline-block rounded-lg bg-accent px-6 py-3 font-stage text-xl font-black text-black"
        >
          Join a game
        </Link>
      </Center>
    );
  }
  if (status === "replaced") {
    return (
      <Center>
        <h1 className="font-stage text-4xl font-black text-white">Opened on another device</h1>
        <p className="mt-3 font-stage text-lg font-bold text-white/80">Your team is now playing on a different computer.</p>
        <button
          onClick={() => {
            useGame.getState().setStatus("connecting");
            setGeneration((g) => g + 1);
          }}
          className="mt-6 rounded-lg bg-accent px-6 py-3 font-stage text-xl font-black text-black"
        >
          Use this computer instead
        </button>
      </Center>
    );
  }
  if (!snap) {
    return (
      <Center>
        <p className="animate-pulse font-stage text-2xl font-black text-white">Connecting…</p>
      </Center>
    );
  }

  const state = snap.game.state;
  const q = snap.question;
  const inQuestion = (state === "open" || state === "paused" || state === "closed" || state === "judging") && q;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between gap-4 border-b-2 border-accent bg-stage-deep px-4 py-1.5 text-white">
        <span className="font-stage text-lg font-black">{BRAND.event}</span>
        <div className="flex items-center gap-4 font-stage text-sm font-bold">
          {!snap.game.judge_ok && <span className="rounded bg-round-yellow px-2 py-0.5 text-black">Judge unavailable, retrying…</span>}
          <span>{snap.me?.name}</span>
          <span className="rounded bg-white/15 px-2 py-0.5 tabular-nums">{fmtPoints(snap.me?.points)} pts</span>
          {snap.me?.rank && (
            <span className="rounded bg-white/15 px-2 py-0.5">
              {ordinal(snap.me.rank)} of {snap.me.teams_total}
            </span>
          )}
        </div>
      </header>
      <main className="min-h-0 flex-1">
        {state === "lobby" && <LobbyView token={token} scope={snap.game.id} />}
        {state === "round_intro" && snap.intro && <RoundIntro intro={snap.intro} compact />}
        {inQuestion && q.type === "multiple_choice" && <McqPlay q={q} token={token} />}
        {inQuestion && q.type !== "multiple_choice" && (
          <div className="relative h-full">
            <Workspace
              key={q.id}
              question={q}
              token={token}
              scope={snap.game.id}
              locked={state === "closed" || state === "judging"}
              lockedMessage={state === "judging" ? "Time's up! Measuring speed…" : "Time's up!"}
              submissions={snap.my_submissions ?? []}
              questionPoints={snap.my_question_points}
            />
            {state === "judging" && (
              <div className="stage-bg absolute inset-0 z-20 opacity-95">
                <MeasuringSpeed />
              </div>
            )}
          </div>
        )}
        {state === "results" && snap.results?.type === "multiple_choice" && (
          <div className="stage-bg h-full overflow-y-auto">
            <McqResults results={snap.results} compact myTeamId={snap.me?.team_id} />
          </div>
        )}
        {state === "results" && snap.results && snap.results.type !== "multiple_choice" && (
          <div className="stage-bg h-full overflow-y-auto">
            <MyResult />
            <ResultsView results={snap.results} compact myTeamId={snap.me?.team_id} />
          </div>
        )}
        {state === "leaderboard" && (
          <div className="stage-bg h-full overflow-y-auto p-6">
            <Leaderboard rows={snap.leaderboard} highlight={snap.me?.team_id} compact limit={20} />
            <p className="mt-6 text-center font-stage text-xl font-bold text-white/80">
              {snap.game.question_index + 1 < snap.game.question_count ? "Get ready for the next question…" : "Waiting for the podium…"}
            </p>
          </div>
        )}
        {(state === "podium" || state === "finished") && (
          <div className="stage-bg flex h-full flex-col">
            <div className="min-h-0 flex-1">
              <Podium rows={snap.podium ?? snap.leaderboard} compact />
            </div>
            {snap.me?.rank && (
              <p className="py-6 text-center font-stage text-3xl font-black text-white">
                You finished {ordinal(snap.me.rank)} with {fmtPoints(snap.me.points)} points
              </p>
            )}
          </div>
        )}
      </main>
      <Toasts />
      <ConnectionBadge />
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <main className="stage-bg flex h-screen flex-col items-center justify-center p-6 text-center">{children}</main>;
}

function MyResult() {
  const snap = useGame((s) => s.snapshot);
  const row = snap?.results?.rows.find((r) => r.team_id === snap.me?.team_id);
  const pos = snap?.results?.rows.findIndex((r) => r.team_id === snap.me?.team_id) ?? -1;
  if (!row) return null;
  return (
    <div className="mx-6 mt-6 rounded-xl bg-white p-5 text-center font-stage text-stage-deep shadow-xl">
      <div className="text-lg font-bold">This round</div>
      <div className="text-5xl font-black">+{fmtPoints(row.points)}</div>
      <div className="text-lg font-bold text-stage-deep/70">
        {pos >= 0 ? `${ordinal(pos + 1)} in the round` : ""}
        {row.class_label ? ` · ${row.class_label}` : ""}
        {row.chars != null && snap?.results?.type === "code_golf" ? ` · ${row.chars} chars` : ""}
      </div>
    </div>
  );
}

function LobbyView({ token, scope }: { token: string; scope: string }) {
  const me = useGame((s) => s.snapshot?.me);
  const [practice, setPractice] = useState<Practice | null>(null);
  useEffect(() => {
    api<Practice>("/practice")
      .then(setPractice)
      .catch(() => setPractice(null));
  }, []);
  return (
    <div className="flex h-full flex-col">
      <div className="stage-bg px-6 py-4 text-center">
        <h1 className="font-stage text-3xl font-black text-white">You&apos;re in, {me?.name}!</h1>
        <p className="font-stage text-lg font-bold text-white/80">Waiting for the teacher to start. Warm up in the editor below: Run works, nothing is scored.</p>
      </div>
      <div className="min-h-0 flex-1">{practice && <Workspace question={practice} token={token} scope={scope} practice />}</div>
    </div>
  );
}
