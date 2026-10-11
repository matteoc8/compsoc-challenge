"use client";
// Host console: one team's code for the current question (their editor right now, and
// every submission) with each hidden test's input, expected and actual output.

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { fmtElapsed } from "@/lib/format";

interface TestResult {
  index: number;
  passed: boolean;
  status: string;
  time_ms: number | null;
  stdin: string;
  expected: string;
  stdout: string;
  stderr: string;
}

interface Work {
  team: { team_id: string; name: string };
  question: { id: string; title: string; type: string };
  draft: { code: string; saved_at: string } | null;
  submissions: {
    attempt: number;
    status: string;
    code: string;
    passed: number | null;
    total: number | null;
    verdict: string | null;
    chars: number;
    elapsed_ms: number;
    error_summary: string | null;
    tests: TestResult[];
  }[];
}

function Pre({ label, text, tone = "" }: { label: string; text: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 text-[11px] font-semibold uppercase text-ink-400">{label}</div>
      <pre className={`max-h-40 overflow-auto rounded border border-ink-600 bg-ink-900 p-2 font-mono text-xs ${tone || "text-ink-200"}`}>{text || " "}</pre>
    </div>
  );
}

export function TeamWork({ gameId, teamId, onClose }: { gameId: string; teamId: string; onClose: () => void }) {
  const [work, setWork] = useState<Work | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<string>("latest");
  const [openTest, setOpenTest] = useState<number | null>(null);

  const load = useCallback(() => {
    api<Work>(`/games/${gameId}/teams/${teamId}/work`)
      .then((w) => {
        setWork(w);
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, [gameId, teamId]);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000); // keep up with a team that's still typing
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const subs = work?.submissions ?? [];
  const sub = tab === "draft" ? null : tab === "latest" ? subs[subs.length - 1] : subs.find((x) => String(x.attempt) === tab);
  const showDraft = tab === "draft" || (tab === "latest" && !subs.length);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal aria-label={`${work?.team.name ?? "Team"}'s code`} onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col rounded-xl bg-ink-800 shadow-2xl ring-1 ring-ink-600" onClick={(e) => e.stopPropagation()}>
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 px-4 py-3">
          <h2 className="mr-auto font-stage text-xl font-black text-white">
            {work?.team.name ?? "…"} <span className="text-sm font-semibold text-ink-400">({work?.question.title})</span>
          </h2>
          <Button size="sm" variant="ghost" onClick={load}>
            Refresh
          </Button>
          <Button size="sm" variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
        {error && <p className="px-4 py-2 text-sm text-fail">{error}</p>}
        {work && (
          <>
            <div className="flex flex-wrap gap-1 border-b border-ink-600 px-4 py-2 text-xs">
              <TabBtn on={tab === "draft"} onClick={() => setTab("draft")}>
                Editor now
              </TabBtn>
              {subs.map((x) => (
                <TabBtn key={x.attempt} on={tab === String(x.attempt) || (tab === "latest" && x === subs[subs.length - 1])} onClick={() => setTab(String(x.attempt))}>
                  #{x.attempt} {x.status === "judged" ? `${x.passed}/${x.total}` : x.status}
                </TabBtn>
              ))}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {showDraft ? (
                work.draft ? (
                  <>
                    <p className="mb-2 text-xs text-ink-400">Autosaved from their editor at {new Date(work.draft.saved_at).toLocaleTimeString("en-GB")} (not submitted).</p>
                    <pre className="overflow-auto rounded border border-ink-600 bg-ink-900 p-3 font-mono text-sm text-white">{work.draft.code}</pre>
                  </>
                ) : (
                  <p className="text-sm text-ink-400">Nothing typed yet.</p>
                )
              ) : sub ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="min-w-0">
                    <div className="mb-2 text-xs text-ink-400">
                      Attempt {sub.attempt} at {fmtElapsed(sub.elapsed_ms)} · {sub.chars} chars · {sub.verdict ?? sub.status}
                      {sub.error_summary && <span className="block text-fail">{sub.error_summary}</span>}
                    </div>
                    <pre className="overflow-auto rounded border border-ink-600 bg-ink-900 p-3 font-mono text-sm text-white">{sub.code}</pre>
                  </div>
                  <div className="min-w-0">
                    <div className="mb-2 text-xs text-ink-400">Hidden tests (click one to see input and output)</div>
                    {!sub.tests.length && <p className="text-sm text-ink-400">{sub.status === "judged" ? "No per-test detail for this submission." : "Still being judged…"}</p>}
                    <div className="mb-3 flex flex-wrap gap-1">
                      {sub.tests.map((t) => (
                        <button
                          key={t.index}
                          onClick={() => setOpenTest(openTest === t.index ? null : t.index)}
                          title={t.status}
                          className={`rounded px-2 py-0.5 font-mono text-xs ${t.passed ? "bg-pass/20 text-pass" : "bg-fail/20 text-fail"} ${openTest === t.index ? "ring-2 ring-white" : ""}`}
                        >
                          {t.index}
                        </button>
                      ))}
                    </div>
                    {sub.tests
                      .filter((t) => t.index === openTest)
                      .map((t) => (
                        <div key={t.index} className="space-y-2">
                          <div className={`text-sm font-bold ${t.passed ? "text-pass" : "text-fail"}`}>
                            Test {t.index}: {t.status}
                            {t.time_ms != null && <span className="ml-2 font-normal text-ink-400">{t.time_ms} ms</span>}
                          </div>
                          <Pre label="Input" text={t.stdin} />
                          <div className="grid gap-2 sm:grid-cols-2">
                            <Pre label="Expected" text={t.expected} />
                            <Pre label="Their output" text={t.stdout} tone={t.passed ? "text-pass" : "text-fail"} />
                          </div>
                          {t.stderr.trim() && <Pre label="Errors" text={t.stderr} tone="text-fail" />}
                        </div>
                      ))}
                  </div>
                </div>
              ) : null}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function TabBtn({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={`rounded px-2.5 py-1 font-semibold ${on ? "bg-round-blue text-white" : "bg-ink-700 text-ink-300 hover:bg-ink-600"}`}>
      {children}
    </button>
  );
}
