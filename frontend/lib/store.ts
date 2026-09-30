// One Zustand store per screen, holding the latest snapshot. Components only read it;
// the socket hook is the only writer.

import { create } from "zustand";
import type { PointsAdjusted, RunResult, Snapshot, SubmissionResult, WsMessage } from "./types";

export type ConnStatus = "connecting" | "open" | "reconnecting" | "unauthorised" | "replaced" | "ended";

export interface Toast {
  id: number;
  text: string;
  tone: "good" | "bad" | "info";
}

interface GameStore {
  status: ConnStatus;
  statusMessage: string | null;
  snapshot: Snapshot | null;
  offset: number; // serverTime - clientTime (ms)
  lastRun: RunResult | null;
  runPending: boolean;
  judging: { done: number; total: number } | null;
  adjustments: (PointsAdjusted & { n: number })[]; // recent, for badges and toasts
  toasts: Toast[];
  solveTick: number; // bumps on each Super Fast solve (projector sting)
  setStatus: (s: ConnStatus, msg?: string | null) => void;
  setOffset: (o: number) => void;
  setRunPending: (p: boolean) => void;
  apply: (m: WsMessage) => void;
  toast: (text: string, tone?: Toast["tone"]) => void;
  dismiss: (id: number) => void;
}

// Stable fallbacks for selectors: a fresh [] or {} each call would re-render forever.
export const EMPTY_LIST: never[] = [];
export const EMPTY_MAP: Record<string, never> = {};

let toastId = 0;
let adjustN = 0;

function upsertSubmission(list: SubmissionResult[] | undefined, s: SubmissionResult): SubmissionResult[] {
  const out = [...(list || [])];
  const i = out.findIndex((x) => x.id === s.id);
  if (i >= 0) out[i] = { ...out[i], ...s };
  else out.push(s);
  return out.sort((a, b) => a.attempt - b.attempt);
}

export const useGame = create<GameStore>((set, get) => ({
  status: "connecting",
  statusMessage: null,
  snapshot: null,
  offset: 0,
  lastRun: null,
  runPending: false,
  judging: null,
  adjustments: [],
  toasts: [],
  solveTick: 0,
  setStatus: (status, msg = null) => set({ status, statusMessage: msg }),
  setOffset: (offset) => set({ offset }),
  setRunPending: (runPending) => set({ runPending }),
  toast: (text, tone = "info") => {
    const id = ++toastId;
    set({ toasts: [...get().toasts, { id, text, tone }] });
    setTimeout(() => get().dismiss(id), 5000);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
  apply: (m) => {
    const snap = get().snapshot;
    switch (m.type) {
      case "snapshot": {
        const next = m.data as Snapshot;
        const judging = next.game.state === "judging" ? get().judging : null;
        set({ snapshot: next, judging });
        return;
      }
      case "timer.update":
        if (snap) set({ snapshot: { ...snap, game: { ...snap.game, ...m.data } } });
        return;
      case "submission.result": {
        if (!snap) return;
        const sub = m.data as SubmissionResult;
        const pts = sub.provisional ? snap.my_question_points : Math.max(snap.my_question_points ?? 0, sub.points ?? 0) || snap.my_question_points;
        set({ snapshot: { ...snap, my_submissions: upsertSubmission(snap.my_submissions, sub), my_question_points: pts } });
        return;
      }
      case "run.result":
        set({ lastRun: m.data as RunResult, runPending: false });
        return;
      case "monitor.update":
        if (snap && snap.question?.id === m.data.question_id) set({ snapshot: { ...snap, monitor: m.data.rows, in_flight: m.data.in_flight } });
        return;
      case "progress.update":
        if (snap && snap.question?.id === m.data.question_id) set({ snapshot: { ...snap, progress: m.data } });
        return;
      case "presence":
        if (snap?.teams) {
          const online = new Set<string>(m.data.online);
          set({ snapshot: { ...snap, teams: snap.teams.map((t) => ({ ...t, online: online.has(t.team_id) })) } });
        }
        return;
      case "judging.progress":
        set({ judging: m.data });
        return;
      case "judge.status":
        if (snap) set({ snapshot: { ...snap, game: { ...snap.game, judge_ok: m.data.ok } } });
        return;
      case "leaderboard.update":
        if (snap) set({ snapshot: { ...snap, leaderboard: m.data.rows } });
        return;
      case "podium":
        if (snap) set({ snapshot: { ...snap, podium: m.data.rows } });
        return;
      case "results":
        if (snap) set({ snapshot: { ...snap, results: m.data } });
        return;
      case "points.adjusted": {
        const a = m.data as PointsAdjusted;
        set({ adjustments: [...get().adjustments.slice(-20), { ...a, n: ++adjustN }] });
        if (snap?.role === "team" && snap.me?.team_id === a.team_id) {
          const sign = a.delta > 0 ? "+" : "";
          get().toast(`${sign}${a.delta}${a.note ? `: ${a.note}` : ""}`, a.delta > 0 ? "good" : "bad");
        }
        return;
      }
      case "solve":
        set({ solveTick: get().solveTick + 1 });
        return;
      case "session.replaced":
        set({ status: "replaced", statusMessage: m.data.message });
        return;
      case "session.ended":
        set({ status: "ended", statusMessage: m.data.message });
        return;
    }
  },
}));
