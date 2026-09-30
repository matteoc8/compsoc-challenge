"use client";
// Projector. Opened from the teacher console with the read-only screen token.

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Leaderboard } from "@/components/leaderboard/Leaderboard";
import { Podium } from "@/components/leaderboard/Podium";
import { McqResults, McqStage } from "@/components/mcq/McqViews";
import { RingCountdown } from "@/components/stage/Countdown";
import { Lobby } from "@/components/stage/Lobby";
import { ProgressStrip } from "@/components/stage/ProgressStrip";
import { MeasuringSpeed, ResultsView } from "@/components/stage/Results";
import { RoundIntro } from "@/components/stage/RoundIntro";
import { ConnectionBadge } from "@/components/ui/ConnectionBadge";
import { Markdown } from "@/components/ui/Markdown";
import { BRAND } from "@/lib/brand";
import { TYPE_ACCENT } from "@/lib/format";
import { useGameSocket } from "@/lib/socket";
import { buzzer, setMuted, sting, unlockAudio } from "@/lib/sound";
import { useGame } from "@/lib/store";

function Presentation() {
  const params = useSearchParams();
  const game = params.get("game");
  const token = params.get("token");
  const [started, setStarted] = useState(false);
  const [muted, setMutedState] = useState(false);
  const wsParams = useMemo(() => (game && token ? { role: "screen", game, token } : null), [game, token]);
  useGameSocket(wsParams);
  const snap = useGame((s) => s.snapshot);
  const status = useGame((s) => s.status);
  const solveTick = useGame((s) => s.solveTick);
  const soundsOn = snap?.settings?.sounds !== false;

  useEffect(() => setMuted(muted), [muted]);

  // Sting on each Super Fast solve, buzzer when a question closes.
  const lastSolve = useRef(solveTick);
  useEffect(() => {
    if (solveTick !== lastSolve.current && started && soundsOn) sting();
    lastSolve.current = solveTick;
  }, [solveTick, started, soundsOn]);
  const lastState = useRef(snap?.game.state);
  useEffect(() => {
    const s = snap?.game.state;
    if (started && soundsOn && lastState.current === "open" && s === "closed") buzzer();
    lastState.current = s;
  }, [snap?.game.state, started, soundsOn]);

  if (!game || !token) return <Message text="Open the projector link from the teacher console." />;
  if (status === "unauthorised") return <Message text="This projector link isn't valid. Open it again from the teacher console." />;

  if (!started) {
    return (
      <main className="stage-bg flex h-screen flex-col items-center justify-center gap-8">
        <h1 className="font-stage text-6xl font-black text-white">{BRAND.event}</h1>
        <button
          onClick={() => {
            unlockAudio();
            setStarted(true);
            document.documentElement.requestFullscreen?.().catch(() => undefined);
          }}
          className="rounded-xl bg-accent px-10 py-5 font-stage text-3xl font-black text-black shadow-2xl hover:bg-accent-light"
        >
          Start presentation
        </button>
        <p className="font-stage text-lg font-bold text-white/70">Unlocks sound and goes full screen. Press Esc to leave full screen.</p>
      </main>
    );
  }

  if (!snap) return <Message text="Connecting…" />;
  const state = snap.game.state;
  const q = snap.question;
  const accent = q ? TYPE_ACCENT[q.type] : "#F6B73C";
  const mcq = q?.type === "multiple_choice";

  return (
    <main className="stage-bg relative h-screen overflow-hidden text-white">
      {state === "lobby" && <Lobby />}
      {state === "round_intro" && snap.intro && <RoundIntro intro={snap.intro} />}
      {(state === "open" || state === "paused" || state === "closed") && q && mcq && (
        <div className="relative h-full">
          <McqStage q={q} sound={soundsOn} />
          {state === "closed" && (
            <div className="absolute inset-0 flex items-center justify-center bg-stage-deep/85">
              <h1 className="animate-pop font-stage text-9xl font-black">Time&apos;s up!</h1>
            </div>
          )}
        </div>
      )}
      {(state === "open" || state === "paused" || state === "closed") && q && !mcq && (
        <div className="flex h-full flex-col gap-6 p-10">
          <div className="flex items-start justify-between gap-8">
            <div className="min-w-0 flex-1">
              <div className="font-stage text-2xl font-extrabold uppercase tracking-widest" style={{ color: "#fff", opacity: 0.8 }}>
                <span className="mr-3 inline-block h-4 w-4 rounded-full align-middle" style={{ background: accent }} />
                {q.round_name}
              </div>
              <h1 className="mt-2 font-stage text-6xl font-black">{q.title}</h1>
              <div className="md-stage mt-4 line-clamp-6 max-w-4xl font-stage text-2xl font-bold leading-snug">
                <Markdown>{q.description_md}</Markdown>
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-center gap-4">
              <RingCountdown size={280} sound={soundsOn} />
              {q.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={q.image_url} alt={q.image_alt || ""} className="max-h-56 max-w-[320px] rounded-lg object-contain shadow-xl" />
              )}
            </div>
          </div>
          <div className="mt-auto rounded-2xl bg-black/25 p-6">
            <ProgressStrip progress={snap.progress} />
          </div>
          {state === "closed" && (
            <div className="absolute inset-0 flex items-center justify-center bg-stage-deep/85">
              <h1 className="animate-pop font-stage text-9xl font-black">Time&apos;s up!</h1>
            </div>
          )}
        </div>
      )}
      {state === "judging" && <MeasuringSpeed />}
      {state === "results" && snap.results?.type === "multiple_choice" && <McqResults results={snap.results} />}
      {state === "results" && snap.results && snap.results.type !== "multiple_choice" && <ResultsView results={snap.results} />}
      {state === "leaderboard" && (
        <div className="h-full overflow-hidden p-10">
          <Leaderboard rows={snap.leaderboard} />
        </div>
      )}
      {(state === "podium" || state === "finished") && <Podium rows={snap.podium ?? snap.leaderboard} />}
      {!snap.game.judge_ok && (
        <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-full bg-round-yellow px-5 py-2 font-stage text-lg font-black text-black">Judge unavailable, retrying…</div>
      )}
      <button
        onClick={() => setMutedState(!muted)}
        className="absolute bottom-4 right-4 rounded-full bg-black/30 px-4 py-2 font-stage text-sm font-bold text-white/80 hover:bg-black/50"
        aria-pressed={muted}
      >
        {muted ? "🔇 Sound off" : "🔊 Sound on"}
      </button>
      <ConnectionBadge />
    </main>
  );
}

function Message({ text }: { text: string }) {
  return (
    <main className="stage-bg flex h-screen items-center justify-center p-8 text-center">
      <p className="font-stage text-3xl font-black text-white">{text}</p>
    </main>
  );
}

export default function PresentationPage() {
  return (
    <Suspense>
      <Presentation />
    </Suspense>
  );
}
