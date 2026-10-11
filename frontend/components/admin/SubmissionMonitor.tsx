"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtElapsed, fmtPoints } from "@/lib/format";
import { EMPTY_LIST, useGame } from "@/lib/store";
import { TeamWork } from "./TeamWork";

const LETTERS = "ABCD";

type Props = { gameId: string; onError: (m: string | null) => void };

export function SubmissionMonitor({ gameId, onError }: Props) {
  const rows = useGame((s) => s.snapshot?.monitor ?? EMPTY_LIST);
  const q = useGame((s) => s.snapshot?.question);
  const state = useGame((s) => s.snapshot?.game.state);
  const [viewing, setViewing] = useState<string | null>(null);
  if (q?.type === "multiple_choice") return <AnswerMonitor gameId={gameId} onError={onError} />;
  const golf = q?.type === "code_golf";
  const visible = rows.filter((r) => !r.kicked);
  const live = state === "open" || state === "paused";
  return (
    <div className="overflow-x-auto rounded-lg bg-ink-800 ring-1 ring-ink-600">
      {live && <HintAll gameId={gameId} onError={onError} />}
      <table className="w-full text-sm">
        <thead className="bg-ink-700 text-left text-xs text-ink-300">
          <tr>
            <th className="px-3 py-2">Team</th>
            <th className="px-2">Attempts</th>
            <th className="px-2">Runs</th>
            <th className="px-2">Best pass rate</th>
            {golf && <th className="px-2">Chars</th>}
            <th className="px-2">First full pass</th>
            <th className="px-3 text-right">Points{q?.type !== "super_fast" ? " (provisional)" : ""}</th>
            <th className="px-3" />
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => (
            <tr key={r.team_id} className="border-t border-ink-700">
              <td className="px-3 py-1.5">
                <span className={`mr-2 inline-block h-2 w-2 rounded-full ${r.online ? "bg-pass" : "bg-ink-500"}`} title={r.online ? "online" : "offline"} />
                <span className="text-white">{r.name}</span>
                {r.in_flight && <span className="ml-2 animate-pulse text-xs text-round-yellow">judging</span>}
              </td>
              <td className="px-2 font-mono">{r.attempts}</td>
              <td className="px-2 font-mono">{r.runs}</td>
              <td className="px-2">
                {r.best_pass_rate == null ? (
                  <span className="text-ink-500">–</span>
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-20 overflow-hidden rounded bg-ink-600">
                      <div className={`h-full ${r.best_pass_rate === 1 ? "bg-pass" : "bg-round-yellow"}`} style={{ width: `${Math.round(r.best_pass_rate * 100)}%` }} />
                    </div>
                    <span className="font-mono text-xs">{Math.round(r.best_pass_rate * 100)}%</span>
                  </div>
                )}
              </td>
              {golf && <td className="px-2 font-mono">{r.best_chars ?? "–"}</td>}
              <td className="px-2 font-mono">{r.first_full_ms != null ? fmtElapsed(r.first_full_ms) : "–"}</td>
              <td className="px-3 text-right font-mono text-white">
                {r.provisional_points != null ? fmtPoints(r.provisional_points) : r.passing && q?.type === "best_complexity" ? "passing" : "–"}
              </td>
              <td className="whitespace-nowrap px-3 text-right">
                <button onClick={() => setViewing(r.team_id)} className="mr-1 rounded bg-ink-600 px-2 py-0.5 text-xs font-semibold text-ink-200 hover:bg-ink-500" title="See their code and each test">
                  Code
                </button>
                {live && <HintMenu gameId={gameId} teamId={r.team_id} given={r.hints ?? []} onError={onError} />}
              </td>
            </tr>
          ))}
          {!visible.length && (
            <tr>
              <td colSpan={8} className="px-3 py-3 text-ink-400">
                No teams.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {viewing && <TeamWork gameId={gameId} teamId={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

async function sendHint(gameId: string, hintIndex: number, teamId: string | null, onError: Props["onError"]) {
  onError(null);
  try {
    await api(`/games/${gameId}/hints`, { body: { hint_index: hintIndex, team_id: teamId } });
  } catch (e) {
    onError(e instanceof ApiError ? e.message : String(e));
  }
}

/** One team: pick which hint to send; ticks show the ones they already have. */
function HintMenu({ gameId, teamId, given, onError }: { gameId: string; teamId: string; given: number[]; onError: Props["onError"] }) {
  const hints = useGame((s) => s.snapshot?.question?.hints ?? EMPTY_LIST) as string[];
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  if (!hints.length) return null;
  const next = hints.findIndex((_, i) => !given.includes(i));
  return (
    <div ref={ref} className="relative inline-block text-left">
      <button
        onClick={() => setOpen(!open)}
        className={`rounded px-2 py-0.5 text-xs font-semibold ${given.length ? "bg-round-yellow/25 text-round-yellow" : "bg-ink-600 text-ink-200 hover:bg-ink-500"}`}
        aria-expanded={open}
        title="Give this team a hint"
      >
        Hints {given.length}/{hints.length}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-72 rounded-md bg-ink-700 p-1 shadow-xl ring-1 ring-ink-500">
          {hints.map((h, i) => (
            <button
              key={i}
              disabled={given.includes(i)}
              onClick={() => {
                setOpen(false);
                void sendHint(gameId, i, teamId, onError);
              }}
              className={`block w-full rounded px-2 py-1.5 text-left text-xs ${given.includes(i) ? "text-ink-400" : "text-white hover:bg-ink-600"} ${i === next ? "font-bold" : ""}`}
            >
              {given.includes(i) ? "✓ " : ""}Hint {i + 1}: <span className="font-normal">{h.length > 70 ? h.slice(0, 70) + "…" : h}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Send a hint to every team that hasn't had it yet. */
function HintAll({ gameId, onError }: Props) {
  const hints = useGame((s) => s.snapshot?.question?.hints ?? EMPTY_LIST) as string[];
  if (!hints.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 px-3 py-2 text-xs">
      <span className="font-semibold uppercase text-ink-400">Hint for everyone</span>
      {hints.map((h, i) => (
        <button key={i} title={h} onClick={() => sendHint(gameId, i, null, onError)} className="rounded bg-ink-600 px-2 py-0.5 font-semibold text-ink-200 hover:bg-ink-500">
          Hint {i + 1}
        </button>
      ))}
      <span className="text-ink-400">Teams that already have it don&apos;t get it twice.</span>
    </div>
  );
}

/** Multiple choice: who has answered, what, and whether it's right (console only). */
function AnswerMonitor({ gameId, onError }: Props) {
  const rows = useGame((s) => s.snapshot?.monitor ?? EMPTY_LIST).filter((r) => !r.kicked);
  const q = useGame((s) => s.snapshot?.question);
  const live = useGame((s) => ["open", "paused"].includes(s.snapshot?.game.state ?? ""));
  const correct = new Set(q?.correct ?? []);
  return (
    <div className="overflow-x-auto rounded-lg bg-ink-800 ring-1 ring-ink-600">
      {live && <HintAll gameId={gameId} onError={onError} />}
      <div className="border-b border-ink-600 px-3 py-2 text-sm text-ink-300">
        Correct answer:{" "}
        <b className="text-pass">
          {(q?.options ?? [])
            .filter((o) => correct.has(o.index))
            .map((o) => `${LETTERS[o.index]}. ${o.text}`)
            .join(" / ")}
        </b>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-ink-700 text-left text-xs text-ink-300">
          <tr>
            <th className="px-3 py-2">Team</th>
            <th className="px-2">Answer</th>
            <th className="px-2">Time</th>
            <th className="px-3" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.team_id} className="border-t border-ink-700">
              <td className="px-3 py-1.5">
                <span className={`mr-2 inline-block h-2 w-2 rounded-full ${r.online ? "bg-pass" : "bg-ink-500"}`} />
                <span className="text-white">{r.name}</span>
              </td>
              <td className={`px-2 font-mono ${r.answered ? (r.correct ? "text-pass" : "text-fail") : "text-ink-500"}`}>
                {r.answered && r.choice != null ? `${LETTERS[r.choice]} ${r.correct ? "" : ""}` : "waiting…"}
              </td>
              <td className="px-2 font-mono">{r.answer_ms != null ? `${(r.answer_ms / 1000).toFixed(1)} s` : "–"}</td>
              <td className="px-3 text-right">{live && <HintMenu gameId={gameId} teamId={r.team_id} given={r.hints ?? []} onError={onError} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
