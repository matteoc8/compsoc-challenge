"use client";
import { useState } from "react";
import { InlineCountdown } from "@/components/stage/Countdown";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { useGame } from "@/lib/store";

const NEXT_LABEL: Record<string, string> = {
  round_intro: "Skip intro",
  results: "Show leaderboard",
  leaderboard: "Next question",
  podium: "Finish game",
};

export function Controls({ gameId, onError }: { gameId: string; onError: (m: string | null) => void }) {
  const snap = useGame((s) => s.snapshot);
  const [busy, setBusy] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [confirmSkip, setConfirmSkip] = useState(false);
  const [confirmForce, setConfirmForce] = useState<string | null>(null);
  const [setRemaining, setSetRemaining] = useState<string | null>(null);
  if (!snap) return null;
  const g = snap.game;
  const state = g.state;

  const call = async (path: string, body: unknown = {}) => {
    setBusy(true);
    onError(null);
    try {
      await api(`/games/${gameId}/${path}`, { body });
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && path === "start" && e.message.includes("No teams")) setConfirmForce(e.message);
      else if (!(e instanceof ApiError && e.message === "The game has already moved on")) onError(e instanceof ApiError ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const running = state === "open" || state === "paused";
  let nextLabel = NEXT_LABEL[state];
  if (state === "leaderboard" && g.question_index + 1 >= g.question_count) nextLabel = "Show podium";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {state === "lobby" && (
          <Button variant="success" size="lg" disabled={busy} onClick={() => call("start", { expect_state: "lobby" })}>
            ▶ Start game
          </Button>
        )}
        {nextLabel && (
          <Button size="lg" disabled={busy} onClick={() => call("next", { expect_state: state })}>
            {nextLabel} →
          </Button>
        )}
        {state === "results" && g.question_index + 1 >= g.question_count && (
          <Button variant="secondary" disabled={busy} onClick={() => call("podium")}>
            Straight to podium
          </Button>
        )}
        {state === "leaderboard" && (
          <Button variant="secondary" disabled={busy} onClick={() => call("results")}>
            ← Back to results
          </Button>
        )}
        {state === "open" && (
          <Button variant="secondary" disabled={busy} onClick={() => call("pause")}>
            ⏸ Pause
          </Button>
        )}
        {state === "paused" && (
          <Button variant="success" disabled={busy} onClick={() => call("resume")}>
            ▶ Resume
          </Button>
        )}
        {running && (
          <Button variant="danger" disabled={busy || g.ending} onClick={() => setConfirmEnd(true)}>
            {g.ending ? "Ending…" : "End now"}
          </Button>
        )}
        {(state === "closed" || state === "judging") && (
          <span className="animate-pulse text-sm text-ink-300">{state === "judging" ? "Benchmarking correct solutions…" : "Waiting for the last submissions to be judged…"}</span>
        )}
        {state === "judging" && (
          <Button variant="secondary" disabled={busy} onClick={() => setConfirmSkip(true)}>
            Skip measuring
          </Button>
        )}
      </div>
      {running && (
        <div className="flex flex-wrap items-center gap-2">
          <InlineCountdown className="mr-2 text-2xl" />
          {[
            [-15, "−15 s"],
            [15, "+15 s"],
            [60, "+1 min"],
          ].map(([d, label]) => (
            <Button key={label} size="sm" variant="secondary" disabled={busy} onClick={() => call("adjust-time", { delta_s: d })}>
              {label}
            </Button>
          ))}
          <Button size="sm" variant="secondary" onClick={() => setSetRemaining("60")}>
            Set remaining…
          </Button>
          {snap.progress && (
            <span className="ml-auto rounded bg-ink-700 px-2 py-1 text-sm font-bold text-white">
              {snap.progress.type === "multiple_choice" ? "Answered" : "Solved"}{" "}
              {snap.progress.type === "multiple_choice" ? snap.progress.answered : snap.progress.passing} / {snap.progress.teams_total}
            </span>
          )}
        </div>
      )}
      <Modal
        open={confirmEnd}
        title="End this question now?"
        onClose={() => setConfirmEnd(false)}
        danger
        confirmLabel="End now"
        busy={busy}
        onConfirm={async () => {
          setConfirmEnd(false);
          await call("end-now");
        }}
      >
        A 3-second &ldquo;Ending…&rdquo; countdown shows on every screen, then nothing new is accepted.
        {snap.in_flight ? (
          <b className="mt-2 block text-round-yellow">
            {snap.in_flight} submission{snap.in_flight === 1 ? " is" : "s are"} still being judged; {snap.in_flight === 1 ? "it" : "they"} will finish and count.
          </b>
        ) : null}
      </Modal>
      <Modal
        open={confirmSkip}
        title="Skip the rest of the measuring?"
        onClose={() => setConfirmSkip(false)}
        confirmLabel="Show results now"
        busy={busy}
        onConfirm={async () => {
          setConfirmSkip(false);
          await call("skip-measuring");
        }}
      >
        Teams already measured keep their result. The rest show as &ldquo;not measured&rdquo; and get the
        lowest share of points; you can set their points on the results screen.
      </Modal>
      <Modal
        open={!!confirmForce}
        title="Start with no teams?"
        onClose={() => setConfirmForce(null)}
        confirmLabel="Start anyway"
        onConfirm={async () => {
          setConfirmForce(null);
          await call("start", { expect_state: "lobby", force: true });
        }}
      >
        {confirmForce}
      </Modal>
      <Modal
        open={setRemaining != null}
        title="Set remaining time"
        onClose={() => setSetRemaining(null)}
        confirmLabel="Set"
        onConfirm={async () => {
          const s = Number(setRemaining);
          setSetRemaining(null);
          if (s >= 1) await call("adjust-time", { set_remaining_s: s });
        }}
      >
        <label className="block">
          Seconds remaining
          <input
            type="number"
            min={1}
            max={3600}
            value={setRemaining ?? ""}
            onChange={(e) => setSetRemaining(e.target.value)}
            className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-white"
            autoFocus
          />
        </label>
      </Modal>
    </div>
  );
}
