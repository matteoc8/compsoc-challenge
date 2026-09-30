"use client";
import { useState } from "react";
import { fmtElapsed, fmtPoints } from "@/lib/format";
import type { QType, RunCase, RunResult, SubmissionResult } from "@/lib/types";
import { OutputDiff } from "./OutputDiff";

type Tab = "result" | "custom" | "submissions";

export function Console({
  run,
  runPending,
  submissions,
  pendingAttempt,
  customInput,
  setCustomInput,
  onRunCustom,
  qtype,
  practice = false,
  disabled = false,
}: {
  run: RunResult | null;
  runPending: boolean;
  submissions: SubmissionResult[];
  pendingAttempt: number | null;
  customInput: string;
  setCustomInput: (s: string) => void;
  onRunCustom: () => void;
  qtype?: QType;
  practice?: boolean;
  disabled?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("result");
  const [openCase, setOpenCase] = useState(0);
  const latest = submissions[submissions.length - 1];
  const judging = pendingAttempt != null || submissions.some((s) => s.status === "queued" || s.status === "running");

  const tabs: [Tab, string][] = [
    ["result", "Test results"],
    ["custom", "Custom input"],
  ];
  if (!practice) tabs.push(["submissions", `Submissions${submissions.length ? ` (${submissions.length})` : ""}`]);

  return (
    <div className="flex h-full flex-col bg-ink-800">
      <div className="flex border-b border-ink-600 text-xs" role="tablist">
        {tabs.map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`px-4 py-2 font-semibold ${tab === k ? "border-b-2 border-round-blue text-white" : "text-ink-400 hover:text-ink-200"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-3 text-sm">
        {!practice && (judging || latest) && tab !== "submissions" && (
          <SubmitBanner sub={judging ? undefined : latest} judging={judging} qtype={qtype} onOpen={() => setTab("submissions")} />
        )}
        {tab === "result" && (
          <div>
            {runPending && <p className="animate-pulse text-ink-300">Running…</p>}
            {!runPending && !run && (
              <p className="text-ink-400">
                <b className="text-ink-200">Run</b> (Ctrl+&apos;) tries your code on the examples. <b className="text-ink-200">Submit</b> (Ctrl+Enter) runs the hidden tests
                {practice ? " (not available in practice)" : " and scores"}.
              </p>
            )}
            {!runPending && run?.error && <p className="text-fail">{run.error}</p>}
            {!runPending && run?.cases && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-1.5">
                  {run.cases.map((c, i) => (
                    <button
                      key={i}
                      onClick={() => setOpenCase(i)}
                      className={`rounded px-2.5 py-1 text-xs font-bold ${openCase === i ? "ring-2 ring-white/60" : ""} ${
                        c.passed === undefined ? "bg-ink-600 text-white" : c.passed ? "bg-pass/20 text-pass" : "bg-fail/20 text-fail"
                      }`}
                    >
                      {run.custom ? "Custom input" : `Example ${c.index}`} {c.passed === undefined ? "" : c.passed ? "✓" : "✗"}
                    </button>
                  ))}
                </div>
                {run.cases[openCase] && <CaseView c={run.cases[openCase]} />}
              </div>
            )}
          </div>
        )}
        {tab === "custom" && (
          <div className="flex h-full flex-col gap-2">
            <label htmlFor="custom-stdin" className="text-xs text-ink-400">
              Your own input (stdin, up to 10 KB). Runs aren&apos;t scored.
            </label>
            <textarea
              id="custom-stdin"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value.slice(0, 10_000))}
              spellCheck={false}
              className="min-h-[90px] flex-1 resize-none rounded border border-ink-600 bg-ink-900 p-2 font-mono text-xs text-ink-200 focus:border-round-blue focus:outline-none"
            />
            <div>
              <button
                onClick={() => {
                  onRunCustom();
                  setTab("result");
                }}
                disabled={runPending || disabled}
                className="rounded bg-ink-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-ink-500 disabled:opacity-40"
              >
                Run with this input
              </button>
            </div>
          </div>
        )}
        {tab === "submissions" && (
          <table className="w-full text-left text-xs">
            <thead className="text-ink-400">
              <tr>
                <th className="py-1">#</th>
                <th>Verdict</th>
                <th>Tests</th>
                {qtype === "code_golf" && <th>Chars</th>}
                <th>At</th>
                <th className="text-right">Points</th>
              </tr>
            </thead>
            <tbody>
              {[...submissions].reverse().map((s) => (
                <tr key={s.id} className="border-t border-ink-700">
                  <td className="py-1.5 font-mono">{s.attempt}</td>
                  <td className={s.verdict === "Accepted" ? "text-pass" : s.status === "judged" ? "text-fail" : "text-ink-300"}>
                    {s.status === "judged" || s.status === "error" ? s.verdict : "Judging…"}
                    {s.first_failed ? ` (test ${s.first_failed})` : ""}
                  </td>
                  <td className="font-mono">{s.total != null ? `${s.passed} / ${s.total}` : "–"}</td>
                  {qtype === "code_golf" && <td className="font-mono">{s.chars}</td>}
                  <td className="font-mono">{fmtElapsed(s.elapsed_ms)}</td>
                  <td className="text-right font-mono">{fmtPoints(s.points)}</td>
                </tr>
              ))}
              {!submissions.length && (
                <tr>
                  <td colSpan={6} className="py-3 text-ink-400">
                    No submissions yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function SubmitBanner({ sub, judging, qtype, onOpen }: { sub?: SubmissionResult; judging: boolean; qtype?: QType; onOpen: () => void }) {
  if (judging)
    return (
      <div className="mb-3 animate-pulse rounded-md border border-ink-500 bg-ink-700 px-3 py-2 text-sm text-ink-200" role="status">
        Judging your submission on the hidden tests…
      </div>
    );
  if (!sub) return null;
  const full = sub.total != null && sub.passed === sub.total && sub.total > 0;
  const tone = sub.status === "error" ? "border-round-yellow bg-round-yellow/10" : full ? "border-pass bg-pass/10" : "border-fail bg-fail/10";
  return (
    <button onClick={onOpen} className={`mb-3 block w-full rounded-md border px-3 py-2 text-left ${tone}`} role="status">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className={`text-base font-bold ${full ? "text-pass" : sub.status === "error" ? "text-round-yellow" : "text-fail"}`}>
          {sub.status === "error" ? "Judge error: try again" : sub.verdict}
          {sub.total != null && <span className="ml-2 font-mono text-white">{sub.passed} / {sub.total} passed</span>}
        </span>
        <span className="font-mono text-sm text-white">
          {sub.points != null ? `${sub.provisional ? "≈ " : ""}${fmtPoints(sub.points)} pts` : qtype === "best_complexity" && full ? "measured at the end" : ""}
        </span>
      </div>
      <div className="mt-0.5 text-xs text-ink-300">
        Attempt {sub.attempt}
        {sub.first_failed ? ` · first failing test: #${sub.first_failed}` : ""}
        {sub.error_summary ? ` · ${sub.error_summary}` : ""}
        {qtype === "code_golf" && full ? ` · ${sub.chars} characters` : ""}
        {sub.provisional && sub.points != null ? " · provisional until time is up" : ""}
      </div>
    </button>
  );
}

function CaseView({ c }: { c: RunCase }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3 text-xs text-ink-400">
        <span className={c.status === "Accepted" ? "text-ink-200" : "font-bold text-fail"}>{c.status === "Accepted" ? "Ran OK" : c.status}</span>
        {c.time_ms != null && <span>{c.time_ms} ms</span>}
        {c.memory_kb != null && <span>{(c.memory_kb / 1024).toFixed(1)} MB</span>}
      </div>
      {c.stdin != null && (
        <div>
          <div className="mb-1 text-[11px] uppercase text-ink-400">Input</div>
          <pre className="max-h-32 overflow-auto rounded bg-ink-900 p-2 font-mono text-xs text-ink-200">{c.stdin || "(empty)"}</pre>
        </div>
      )}
      {c.expected !== undefined ? (
        <OutputDiff expected={c.expected} actual={c.stdout} />
      ) : (
        <div>
          <div className="mb-1 text-[11px] uppercase text-ink-400">Output</div>
          <pre className="max-h-48 overflow-auto rounded bg-ink-900 p-2 font-mono text-xs text-ink-200">{c.stdout || "(no output)"}</pre>
        </div>
      )}
      {c.stderr && (
        <div>
          <div className="mb-1 text-[11px] uppercase text-fail">Error</div>
          <pre className="max-h-48 overflow-auto rounded bg-fail/10 p-2 font-mono text-xs text-fail">{c.stderr}</pre>
        </div>
      )}
    </div>
  );
}
