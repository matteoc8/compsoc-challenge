"use client";
// The LeetCode-style workspace: problem on the left, editor top-right, console bottom-right.

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useRemaining } from "@/components/stage/Countdown";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { fmtElapsed, fmtPoints } from "@/lib/format";
import { golfChars } from "@/lib/golf";
import { formatPython, preloadRuff } from "@/lib/ruff";
import { superFastEstimate } from "@/lib/scoring";
import { useGame } from "@/lib/store";
import type { PublicQuestion, SubmissionResult } from "@/lib/types";
import { Console } from "./Console";
import { ProblemPane } from "./ProblemPane";

const CodeEditor = dynamic(() => import("./CodeEditor"), {
  ssr: false,
  loading: () => <div className="h-full bg-[#1e1e1e] p-4 font-mono text-sm text-ink-400">Loading editor…</div>,
});

const DRAFT_EVERY_MS = 10_000;
const MAX_ATTEMPTS = 20;

type Q = Pick<PublicQuestion, "round_name" | "title" | "description_md"> & Partial<PublicQuestion> & { id: string };

function localKey(scope: string, qid: string) {
  return `cc_draft:${scope}:${qid}`;
}

function readLocal(key: string): { code: string; t: number } | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeLocal(key: string, code: string) {
  try {
    localStorage.setItem(key, JSON.stringify({ code, t: Date.now() }));
  } catch {
    /* storage full or blocked: the server draft still works */
  }
}

export function Workspace({
  question,
  token,
  scope,
  practice = false,
  locked = false,
  lockedMessage,
  submissions = [],
  questionPoints,
}: {
  question: Q;
  token: string;
  scope: string; // game id, for local draft keys
  practice?: boolean;
  locked?: boolean; // closed / judging: read-only
  lockedMessage?: string;
  submissions?: SubmissionResult[];
  questionPoints?: number | null;
}) {
  const starter = question.starter_code ?? "";
  const [code, setCode] = useState<string | null>(null);
  const [customInput, setCustomInput] = useState(question.examples?.[0]?.stdin ?? "");
  const [pendingAttempt, setPendingAttempt] = useState<number | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [formatError, setFormatError] = useState<string | null>(null);
  const lastRun = useGame((s) => s.lastRun);
  const runPending = useGame((s) => s.runPending);
  const setRunPending = useGame((s) => s.setRunPending);
  const toast = useGame((s) => s.toast);
  const paused = useGame((s) => s.snapshot?.game.paused ?? false);
  const dirty = useRef(false);
  const codeRef = useRef<string>("");
  const key = localKey(scope, question.id);

  // Restore: newest of the server draft and the local copy, else the starter code.
  useEffect(() => {
    let cancelled = false;
    setCode(null);
    useGame.setState({ lastRun: null, runPending: false });
    preloadRuff();
    const local = readLocal(key);
    (async () => {
      let server: { code: string | null; saved_at: string | null } = { code: null, saved_at: null };
      if (!practice) {
        try {
          server = await api(`/drafts/${question.id}`, { token });
        } catch {
          /* offline: fall back to the local copy */
        }
      }
      if (cancelled) return;
      const serverT = server.saved_at ? Date.parse(server.saved_at) : 0;
      const initial = local && local.t >= serverT ? local.code : server.code ?? local?.code ?? starter;
      codeRef.current = initial;
      setCode(initial);
    })();
    return () => {
      cancelled = true;
    };
  }, [key, question.id, practice, token, starter]);

  const saveDraft = useCallback(async () => {
    if (practice || !dirty.current) return;
    dirty.current = false;
    try {
      await api(`/drafts/${question.id}`, { method: "PUT", body: { code: codeRef.current }, token });
    } catch {
      dirty.current = true; // retry on the next tick
    }
  }, [practice, question.id, token]);

  useEffect(() => {
    const id = setInterval(saveDraft, DRAFT_EVERY_MS);
    const flush = () => void saveDraft();
    window.addEventListener("beforeunload", flush);
    return () => {
      clearInterval(id);
      window.removeEventListener("beforeunload", flush);
      void saveDraft();
    };
  }, [saveDraft]);

  const onChange = useCallback(
    (v: string) => {
      codeRef.current = v;
      setCode(v);
      dirty.current = true;
      writeLocal(key, v);
    },
    [key],
  );

  // Clear the "judging" flag once the result for that attempt arrives.
  useEffect(() => {
    if (pendingAttempt == null) return;
    const s = submissions.find((x) => x.attempt === pendingAttempt);
    if (s && (s.status === "judged" || s.status === "error")) setPendingAttempt(null);
  }, [submissions, pendingAttempt]);

  // Safety net: never leave "Running…" up forever.
  useEffect(() => {
    if (!runPending) return;
    const t = setTimeout(() => {
      if (useGame.getState().runPending) {
        setRunPending(false);
        toast("The run took too long to come back. Try again.", "bad");
      }
    }, 45_000);
    return () => clearTimeout(t);
  }, [runPending, setRunPending, toast]);

  const doRun = useCallback(
    async (stdin?: string) => {
      if (locked || useGame.getState().runPending) return;
      setRunPending(true);
      void saveDraft();
      try {
        await api("/runs", { body: { question_id: question.id, code: codeRef.current, stdin: stdin ?? null }, token });
      } catch (e) {
        setRunPending(false);
        toast(e instanceof ApiError ? e.message : "Run failed", "bad");
      }
    },
    [locked, question.id, token, saveDraft, setRunPending, toast],
  );

  const submitting = useRef(false);
  const doSubmit = useCallback(async () => {
    if (practice || locked || pendingAttempt != null || submitting.current) return;
    submitting.current = true;
    void saveDraft();
    try {
      const r = await api<{ attempt: number }>("/submissions", { body: { question_id: question.id, code: codeRef.current }, token });
      setPendingAttempt(r.attempt);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Submit failed", "bad");
    } finally {
      submitting.current = false;
    }
  }, [practice, locked, pendingAttempt, question.id, token, saveDraft, toast]);

  const doFormat = useCallback(async () => {
    const r = await formatPython(codeRef.current);
    if (r.ok && r.code != null) {
      onChange(r.code);
      setFormatError(null);
    } else setFormatError("Can't format: fix the syntax errors first.");
  }, [onChange]);

  // Shortcuts also work when focus is outside the editor.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // the editor's own keymap already handled it (and called preventDefault)
      if (e.defaultPrevented || !(e.ctrlKey || e.metaKey)) return;
      if (e.key === "'") {
        e.preventDefault();
        void doRun();
      } else if (e.key === "Enter") {
        e.preventDefault();
        void doSubmit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doRun, doSubmit]);

  // Shift+Alt+F formats (not in Code Golf)
  useEffect(() => {
    if (question.type === "code_golf") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.shiftKey && e.altKey && (e.key === "F" || e.key === "f")) {
        e.preventDefault();
        void doFormat();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doFormat, question.type]);

  const judging = pendingAttempt != null || submissions.some((s) => s.status === "queued" || s.status === "running");
  const attemptsLeft = MAX_ATTEMPTS - submissions.length;

  return (
    <div className="relative h-full">
      <PanelGroup direction="horizontal" autoSaveId="cc-ws-h">
        <Panel defaultSize={36} minSize={20}>
          <ProblemPane q={question} attempts={submissions.length} maxAttempts={MAX_ATTEMPTS} points={questionPoints} practice={practice} />
        </Panel>
        <PanelResizeHandle className="w-1.5 bg-ink-700 transition hover:bg-round-blue" />
        <Panel minSize={30}>
          <PanelGroup direction="vertical" autoSaveId="cc-ws-v">
            <Panel defaultSize={64} minSize={25}>
              <div className="flex h-full flex-col">
                <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 bg-ink-800 px-3 py-1.5">
                  <span className="font-mono text-xs text-ink-400">solution.py</span>
                  {question.type === "code_golf" && code != null && <GolfCounter code={code} />}
                  {question.type === "super_fast" && !practice && question.scoring?.mode === "ranked" && <PlacesMeter />}
                  {question.type === "super_fast" && !practice && question.scoring?.mode === "speed_weighted" && (
                    <SpeedMeter scoring={question.scoring} limitS={question.time_limit_s ?? 240} />
                  )}
                  <div className="ml-auto flex items-center gap-1.5">
                    {question.type !== "code_golf" && (
                      <button onClick={doFormat} disabled={locked} className="rounded px-2 py-1 text-xs text-ink-300 hover:bg-ink-700 disabled:opacity-40" title="Shift+Alt+F">
                        Format
                      </button>
                    )}
                    <button onClick={() => setConfirmReset(true)} disabled={locked} className="rounded px-2 py-1 text-xs text-ink-300 hover:bg-ink-700 disabled:opacity-40">
                      Reset
                    </button>
                    <button
                      onClick={() => doRun()}
                      disabled={locked || runPending}
                      className="rounded-md bg-ink-600 px-3.5 py-1.5 text-sm font-bold text-white hover:bg-ink-500 disabled:opacity-40"
                      title="Ctrl+'"
                    >
                      {runPending ? "Running…" : "▶ Run"} <span className="ml-1 hidden text-[10px] font-normal text-ink-300 lg:inline">Ctrl+&apos;</span>
                    </button>
                    {!practice && (
                      <button
                        onClick={doSubmit}
                        disabled={locked || judging || paused || attemptsLeft <= 0}
                        className="rounded-md bg-pass px-3.5 py-1.5 text-sm font-bold text-white hover:brightness-110 disabled:opacity-40"
                        title={paused ? "Paused" : "Ctrl+Enter"}
                      >
                        {judging ? "Judging…" : "Submit"} <span className="ml-1 hidden text-[10px] font-normal text-white/80 lg:inline">Ctrl+Enter</span>
                      </button>
                    )}
                  </div>
                </div>
                {formatError && (
                  <div className="flex items-center justify-between bg-fail/15 px-3 py-1 text-xs text-fail">
                    {formatError}
                    <button onClick={() => setFormatError(null)} aria-label="Dismiss">
                      ✕
                    </button>
                  </div>
                )}
                <div className="min-h-0 flex-1 bg-[#1e1e1e]">
                  {code != null && (
                    <CodeEditor value={code} onChange={onChange} onRun={() => doRun()} onSubmit={doSubmit} readOnly={locked} autoFocus />
                  )}
                </div>
              </div>
            </Panel>
            <PanelResizeHandle className="h-1.5 bg-ink-700 transition hover:bg-round-blue" />
            <Panel defaultSize={36} minSize={15}>
              <Console
                run={lastRun}
                runPending={runPending}
                submissions={submissions}
                pendingAttempt={pendingAttempt}
                customInput={customInput}
                setCustomInput={setCustomInput}
                onRunCustom={() => doRun(customInput)}
                qtype={question.type}
                practice={practice}
                disabled={locked}
              />
            </Panel>
          </PanelGroup>
        </Panel>
      </PanelGroup>
      {locked && lockedMessage && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex justify-center pt-2">
          <div className="rounded-full bg-round-red px-5 py-1.5 font-stage text-sm font-extrabold text-white shadow-lg">{lockedMessage}</div>
        </div>
      )}
      {paused && !locked && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex justify-center pt-2">
          <div className="rounded-full bg-round-yellow px-5 py-1.5 font-stage text-sm font-extrabold text-black shadow-lg">
            Paused: keep coding, Submit opens when the game resumes
          </div>
        </div>
      )}
      <Modal
        open={confirmReset}
        title="Reset to starter code?"
        onClose={() => setConfirmReset(false)}
        onConfirm={() => {
          onChange(starter);
          setConfirmReset(false);
        }}
        confirmLabel="Reset"
        danger
      >
        Your current code will be replaced. Earlier submissions are kept.
      </Modal>
    </div>
  );
}

function GolfCounter({ code }: { code: string }) {
  const n = golfChars(code);
  const best = useGame((s) => s.snapshot?.progress?.best_chars);
  return (
    <span className="rounded bg-round-blue/20 px-2 py-0.5 font-mono text-xs font-bold text-white" title="Counted exactly as the judge counts">
      {n} chars{best != null ? <span className="ml-2 font-normal text-ink-300">best so far: {best}</span> : null}
    </span>
  );
}

function PlacesMeter() {
  const progress = useGame((s) => s.snapshot?.progress);
  const places = progress?.place_points ?? [];
  const taken = Math.min(progress?.solves?.length ?? 0, places.length);
  const left = places.length - taken;
  return (
    <span className="flex items-center gap-2 rounded bg-round-red/20 px-2 py-0.5 text-xs text-white">
      <b className="font-mono tabular-nums">
        {left} of {places.length}
      </b>
      <span className="text-ink-300">
        {left > 0 ? (
          <>
            places left · next solve earns <b className="font-mono text-white">{places[taken]?.toLocaleString("en-GB")}</b>
          </>
        ) : (
          "places taken"
        )}
      </span>
    </span>
  );
}

function SpeedMeter({ scoring, limitS }: { scoring?: Record<string, unknown>; limitS: number }) {
  const { ms } = useRemaining();
  const limit = limitS * 1000;
  const elapsed = ms == null ? 0 : Math.max(0, limit - ms);
  const now = superFastEstimate(scoring, elapsed, limit, 1);
  return (
    <span className="flex items-center gap-2 rounded bg-round-red/20 px-2 py-0.5 text-xs text-white">
      <span className="font-mono font-bold tabular-nums">{fmtElapsed(elapsed)}</span>
      <span className="text-ink-300">
        submit now for up to <b className="font-mono text-white">{fmtPoints(now)}</b> pts
      </span>
    </span>
  );
}
