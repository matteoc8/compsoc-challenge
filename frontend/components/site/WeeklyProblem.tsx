"use client";
// One problem of the week: the statement, an editor with Run (examples) and Submit, your own
// results, and this week's standings. You enter with your full name and school email once; the
// server ties the name to the email, and this browser remembers it.

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Examples } from "@/components/site/problems";
import { Button } from "@/components/ui/Button";
import { Rank } from "@/components/ui/Rank";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import { fmtBenchMs, fmtElapsed, fmtPoints, timeLeft } from "@/lib/format";
import { golfChars } from "@/lib/golf";
import type { IOCase } from "@/lib/types";
import { YEAR_GROUPS, yearLabel, type YearGroup } from "@/lib/years";

const CodeEditor = dynamic(() => import("@/components/workspace/CodeEditor"), { ssr: false, loading: () => <div className="h-72 rounded bg-[#1e1e1e]" /> });

export interface WeeklySummary {
  id: string;
  title: string;
  type: "super_fast" | "code_golf" | "best_complexity";
  opens_at: string;
  closes_at: string;
  phase: "upcoming" | "open" | "closed";
  credit: string | null;
}

interface Standing {
  rank: number;
  name: string;
  passed: number | null;
  total: number | null;
  points: number;
  chars: number | null;
  class_label: string | null;
  time_ms: number | null;
  floor_ms?: number | null;
  solved_after_ms: number | null;
}

interface Detail extends WeeklySummary {
  question: { title: string; description_md: string; examples: IOCase[]; starter_code: string; tests_total: number; image_url: string | null; image_alt: string | null };
  rule: string;
  standings: Standing[];
  solution?: string;
  email_domain: string | null;
}

interface Identity {
  name: string;
  email: string;
  year_group?: YearGroup | null;
}

interface Mine {
  standing: Standing | null;
  submissions: { id: number; status: string; passed: number | null; total: number | null; verdict: string | null; first_failed: number | null; error_summary: string | null; chars: number; class_label: string | null; time_ms: number | null; submitted_at: string }[];
}

interface RunCase {
  index: number;
  stdin: string;
  expected: string;
  stdout: string;
  stderr: string;
  status: string;
  passed: boolean;
}

/** Names on the weekly side. The Challenge game keeps its own names (Best Time Complexity etc.).
 *  Super Fast is no longer offered for new weeks but older weeks may still be one. */
export const WEEKLY_TYPES: Record<WeeklySummary["type"], { name: string; rule: string; measure: string }> = {
  best_complexity: { name: "Fastest Code", rule: "quickest execution wins", measure: "Time" },
  code_golf: { name: "Code Golf", rule: "shortest code wins", measure: "Length" },
  super_fast: { name: "Super Fast", rule: "first to solve it wins", measure: "Solved" },
};

/** e.g. "Code Golf (shortest code wins)" */
export function weeklyType(type: WeeklySummary["type"]): string {
  return `${WEEKLY_TYPES[type].name} (${WEEKLY_TYPES[type].rule})`;
}

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode */
  }
}

export function measureCell(type: WeeklySummary["type"], r: { chars: number | null; class_label: string | null; time_ms: number | null; floor_ms?: number | null; solved_after_ms?: number | null; passed: number | null; total: number | null }) {
  const full = r.total != null && r.passed === r.total;
  if (type === "code_golf") return r.chars != null ? `${r.chars} chars` : "–";
  if (type === "best_complexity") return !full ? "–" : r.time_ms != null ? fmtBenchMs(r.time_ms, r.floor_ms ?? 0) : (r.class_label ?? "measuring…");
  return r.solved_after_ms != null ? `solved after ${fmtElapsed(r.solved_after_ms)}` : "–";
}

export function StandingsTable({ rows, type, highlight }: { rows: Standing[]; type: WeeklySummary["type"]; highlight?: string }) {
  if (!rows.length) return <p className="rounded-md bg-ink-800 p-4 text-sm text-ink-400">No entries yet. Be the first!</p>;
  return (
    <div className="overflow-x-auto rounded-lg ring-1 ring-ink-600">
      <table className="w-full text-sm">
        <thead className="bg-ink-700 text-left text-xs text-ink-300">
          <tr>
            <th className="px-3 py-2">#</th>
            <th className="px-2">Name</th>
            <th className="px-2">Tests</th>
            <th className="px-2">{WEEKLY_TYPES[type].measure}</th>
            <th className="px-3 text-right">Points</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`border-t border-ink-700 ${highlight && r.name === highlight ? "bg-round-blue/15" : "bg-ink-800"}`}>
              <td className="px-3 py-1.5">
                <Rank rank={r.rank} />
              </td>
              <td className="px-2 text-white">{r.name}</td>
              <td className={`px-2 tabular-nums ${r.passed === r.total ? "text-pass" : "text-round-yellow"}`}>
                {r.passed}/{r.total}
              </td>
              <td className="px-2 tabular-nums text-ink-200">{measureCell(type, r)}</td>
              <td className="px-3 text-right tabular-nums text-white">{fmtPoints(r.points)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function WeeklyProblem({ id }: { id: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [who, setWho] = useState<Identity | null>(null); // checked by the server
  const [form, setForm] = useState<Identity>({ name: "", email: "" });
  const [signError, setSignError] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [mine, setMine] = useState<Mine | null>(null);
  const [cases, setCases] = useState<RunCase[] | null>(null);
  const [busy, setBusy] = useState<"run" | "submit" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const poll = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(() => {
    api<Detail>(`/weekly/${id}`)
      .then((d) => {
        setDetail(d);
        setCode((c) => c ?? load<string>(`potw_code_${id}`, d.question.starter_code || ""));
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load the problem"));
  }, [id]);

  const refreshMine = useCallback(
    async (email: string) => {
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return;
      try {
        const m = await api<Mine>(`/weekly/${id}/mine?email=${encodeURIComponent(email)}`);
        setMine(m);
        if (poll.current) clearTimeout(poll.current);
        if (m.submissions.some((x) => ["queued", "running", "measuring"].includes(x.status))) {
          poll.current = setTimeout(() => void refreshMine(email), 1500);
        } else if (poll.current) {
          poll.current = null;
          setNotice((n) => (n?.startsWith("Submitted") ? null : n));
          refresh(); // judging finished: the standings may have changed
        }
      } catch {
        /* keep the last result */
      }
    },
    [id, refresh],
  );

  const signIn = useCallback(
    async (form: Identity, quiet = false) => {
      setSignError(null);
      try {
        const me = await api<Identity>("/weekly/sign-in", { body: form });
        save("potw_identity", me);
        setWho(me);
        void refreshMine(me.email);
      } catch (e) {
        setWho(null);
        setMine(null);
        if (!quiet || (e instanceof ApiError && [403, 409, 422].includes(e.status))) {
          setSignError(e instanceof ApiError ? e.message : String(e));
        }
      }
    },
    [refreshMine],
  );

  useEffect(() => {
    refresh();
    const saved = load<Identity>("potw_identity", { name: "", email: "" });
    setForm(saved);
    if (saved.name && saved.email) void signIn(saved, true);
    return () => {
      if (poll.current) clearTimeout(poll.current);
    };
  }, [refresh, signIn]);

  if (error && !detail) return <p className="text-ink-300">{error}</p>;
  if (!detail || code == null) return <p className="text-ink-400">Loading…</p>;
  const open = detail.phase === "open";
  const q = detail.question;

  const run = async () => {
    setBusy("run");
    setNotice(null);
    try {
      setCases((await api<{ cases: RunCase[] }>(`/weekly/${id}/run`, { body: { code } })).cases);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const signOut = () => {
    save("potw_identity", { name: "", email: "" });
    setWho(null);
    setMine(null);
    setForm({ name: "", email: "" });
  };

  const submit = async () => {
    if (!who) return;
    setBusy("submit");
    setNotice(null);
    try {
      const r = await api<{ submissions_left: number }>(`/weekly/${id}/submit`, { body: { ...who, code } });
      setNotice(`Submitted. Judging… (${r.submissions_left} submissions left this week)`);
      await refreshMine(who.email);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 409) && !e.message.includes("closed")) {
        setWho(null);
        setSignError(e.message);
      } else setNotice(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const input = "w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-white focus:border-round-blue focus:outline-none";
  const last = mine?.submissions[mine.submissions.length - 1];

  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-wide">
          <span className="rounded bg-accent px-2 py-0.5 text-black">Problem of the week</span>
          <span className="text-ink-300">{weeklyType(detail.type)}</span>
          <span className={open ? "text-pass" : "text-ink-400"}>
            {open ? timeLeft(detail.closes_at) : `Closed ${new Date(detail.closes_at).toLocaleDateString("en-GB")}`}
          </span>
        </div>
        <h1 className="mt-2 font-stage text-4xl font-black text-white">{q.title}</h1>
        {detail.credit && <p className="mt-1 text-sm text-ink-400">{detail.credit}</p>}
        <p className="mt-1 text-sm text-ink-300">{detail.rule}</p>
      </div>
      <Markdown className="text-ink-200">{q.description_md}</Markdown>
      {q.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={q.image_url} alt={q.image_alt || ""} className="max-h-72 rounded-lg" />
      )}
      <Examples examples={q.examples} />

      {open && (
        <section className="space-y-3 rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
          {who ? (
            <p className="text-sm text-ink-300">
              Entering as <b className="text-white">{who.name}</b> ({yearLabel(who.year_group)})
              <button className="ml-3 text-xs text-ink-400 underline hover:text-white" onClick={signOut}>
                Not you?
              </button>
            </p>
          ) : (
            <form
              className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto_auto]"
              onSubmit={(e) => {
                e.preventDefault();
                void signIn(form);
              }}
            >
              <label className="block text-sm font-semibold text-white">
                Full name
                <input className={`${input} mt-1`} value={form.name} maxLength={60} autoComplete="name" onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label className="block text-sm font-semibold text-white">
                School email <span className="font-normal text-ink-400">(never shown)</span>
                <input
                  className={`${input} mt-1`}
                  type="email"
                  value={form.email}
                  maxLength={200}
                  autoComplete="email"
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </label>
              <label className="block text-sm font-semibold text-white">
                Year
                <select className={`${input} mt-1`} value={form.year_group ?? ""} onChange={(e) => setForm({ ...form, year_group: (e.target.value || null) as YearGroup | null })}>
                  <option value="">Choose…</option>
                  {YEAR_GROUPS.map((y) => (
                    <option key={y.id} value={y.id}>
                      {y.label}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" disabled={form.name.trim().split(/\s+/).length < 2 || !form.email.includes("@") || !form.year_group}>
                Enter
              </Button>
              {signError && <p className="text-sm text-fail sm:col-span-4">{signError}</p>}
            </form>
          )}
          <div className="flex items-center justify-between text-xs text-ink-400">
            <span>Python 3.8 (reads from input(), prints the answer)</span>
            {detail.type === "code_golf" && <span className="tabular-nums text-white">{golfChars(code)} chars</span>}
          </div>
          <div className="h-72 overflow-hidden rounded border border-ink-600">
            <CodeEditor
              value={code}
              onChange={(v) => {
                setCode(v);
                save(`potw_code_${id}`, v);
              }}
              ariaLabel="Your solution"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" disabled={!!busy} onClick={run}>
              {busy === "run" ? "Running…" : "▶ Run examples"}
            </Button>
            <Button variant="success" disabled={!!busy || !who || !code.trim()} onClick={submit}>
              {busy === "submit" ? "Sending…" : "Submit"}
            </Button>
          </div>
          {notice && <p className="text-sm text-round-yellow">{notice}</p>}
          {cases && (
            <div className="space-y-2">
              {cases.map((c) => (
                <details key={c.index} className="rounded border border-ink-600 bg-ink-900 p-2 text-sm" open={!c.passed}>
                  <summary className={`cursor-pointer font-semibold ${c.passed ? "text-pass" : "text-fail"}`}>
                    Example {c.index}: {c.passed ? "passed" : c.status === "Accepted" ? "wrong answer" : c.status}
                  </summary>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <pre className="overflow-auto font-mono text-xs text-ink-200">Expected:{"\n"}{c.expected}</pre>
                    <pre className="overflow-auto font-mono text-xs text-white">Yours:{"\n"}{c.stdout}</pre>
                  </div>
                  {c.stderr.trim() && <pre className="mt-2 overflow-auto font-mono text-xs text-fail">{c.stderr}</pre>}
                </details>
              ))}
            </div>
          )}
        </section>
      )}

      {mine && mine.submissions.length > 0 && (
        <section>
          <h2 className="mb-2 font-stage text-xl font-black text-white">Your submissions</h2>
          {mine.standing && (
            <p className="mb-2 text-sm text-ink-200">
              You&apos;re <b className="text-white">#{mine.standing.rank}</b> this week with <b className="text-white">{fmtPoints(mine.standing.points)}</b> points.
            </p>
          )}
          <ul className="space-y-1 text-sm">
            {[...mine.submissions].reverse().map((x) => (
              <li key={x.id} className="flex flex-wrap items-center gap-3 rounded bg-ink-800 px-3 py-1.5">
                <span className="text-xs text-ink-400">{new Date(x.submitted_at).toLocaleString("en-GB")}</span>
                {["queued", "running", "measuring"].includes(x.status) ? (
                  <span className="animate-pulse text-round-yellow">{x.status === "measuring" ? "measuring speed…" : "judging…"}</span>
                ) : (
                  <span className={x.passed === x.total ? "font-bold text-pass" : "text-round-yellow"}>
                    {x.passed}/{x.total} tests{x.passed !== x.total && x.verdict ? ` (${x.verdict}${x.first_failed ? ` on test ${x.first_failed}` : ""})` : ""}
                  </span>
                )}
                {detail.type === "code_golf" && <span className="tabular-nums text-ink-200">{x.chars} chars</span>}
                {x.class_label && <span className="text-ink-200">{x.class_label}</span>}
                {x.error_summary && <span className="tabular-nums text-xs text-fail">{x.error_summary}</span>}
              </li>
            ))}
          </ul>
          {last && last.status === "error" && <p className="mt-1 text-xs text-fail">The judge had a problem with that one. Try submitting again.</p>}
        </section>
      )}

      <section>
        <div className="mb-2 flex items-end justify-between">
          <h2 className="font-stage text-xl font-black text-white">This week&apos;s leaderboard</h2>
          <Link href="/weekly/leaderboard" className="text-sm text-round-blue hover:underline">
            School leaderboard →
          </Link>
        </div>
        <StandingsTable rows={detail.standings} type={detail.type} highlight={mine?.standing?.name} />
      </section>

      {detail.solution != null && (
        <section>
          <h2 className="mb-2 font-stage text-xl font-black text-white">Solution</h2>
          <pre className="overflow-x-auto rounded-md border border-ink-600 bg-ink-900 p-4 font-mono text-sm text-white">{detail.solution}</pre>
        </section>
      )}
    </div>
  );
}
