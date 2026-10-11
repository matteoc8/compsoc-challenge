"use client";
// One person: their details, every week they entered with each submission's code, and tools to
// fix their name or year, ban them, remove a submission or a whole week, or delete everything.

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { AdminNav } from "@/components/admin/AdminNav";
import { measureCell, WEEKLY_TYPES } from "@/components/site/WeeklyProblem";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { useAdmin } from "@/lib/admin";
import { fmtPoints } from "@/lib/format";
import { YEAR_GROUPS, yearLabel, type Person } from "@/lib/years";

interface Submission {
  id: number;
  code: string;
  status: string;
  passed: number | null;
  total: number | null;
  verdict: string | null;
  chars: number | null;
  class_label: string | null;
  time_ms: number | null;
  submitted_at: string;
}

interface Week {
  id: string;
  title: string;
  type: "super_fast" | "code_golf" | "best_complexity";
  opens_at: string;
  closes_at: string;
  phase: string;
  rank: number | null;
  points: number;
  submissions: Submission[];
}

interface Detail extends Person {
  total_points: number;
  weeks_detail: Week[];
}

type Confirm = { kind: "entry"; id: number } | { kind: "week"; week: Week } | { kind: "all" };

export default function PersonPage() {
  return (
    <Suspense>
      <PersonView />
    </Suspense>
  );
}

function PersonView() {
  const me = useAdmin();
  const router = useRouter();
  const email = useSearchParams().get("email") ?? "";
  const [d, setD] = useState<Detail | null>(null);
  const [edit, setEdit] = useState<{ name: string; year_group: string }>({ name: "", year_group: "" });
  const [openCode, setOpenCode] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Detail>(`/weekly-admin/people/detail?email=${encodeURIComponent(email)}`)
      .then((x) => {
        setD(x);
        setEdit({ name: x.name, year_group: x.year_group ?? "" });
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, [email]);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  const act = async (fn: () => Promise<unknown>, after: () => void = load) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      after();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };
  const save = (change: { banned?: boolean } = {}) =>
    act(() => api("/weekly-admin/people", { method: "PUT", body: { email, name: edit.name, year_group: edit.year_group || null, banned: d?.banned, ...change } }));
  const runConfirm = () => {
    if (!confirm) return;
    if (confirm.kind === "entry") void act(() => api(`/weekly-admin/entries/${confirm.id}`, { method: "DELETE" }));
    else if (confirm.kind === "week") void act(() => api(`/weekly-admin/people/week?email=${encodeURIComponent(email)}&weekly_id=${confirm.week.id}`, { method: "DELETE" }));
    else void act(() => api(`/weekly-admin/people?email=${encodeURIComponent(email)}`, { method: "DELETE" }), () => router.push("/admin/people"));
  };

  if (!me) return null;
  const input = "rounded-md border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none";
  const changed = d && (edit.name.trim() !== d.name || (edit.year_group || null) !== d.year_group);

  return (
    <main className="mx-auto min-h-full max-w-6xl p-6">
      <AdminNav me={me} />
      <Link href="/admin/people" className="text-sm text-ink-400 hover:text-white">
        ← People
      </Link>
      {error && (
        <div className="my-4 rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </div>
      )}
      {!d && !error && <p className="mt-4 text-ink-400">Loading…</p>}
      {d && (
        <div className="mt-3 space-y-6">
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-2xl font-bold text-white">{d.name}</h1>
            <span className="text-ink-300">{yearLabel(d.year_group)}</span>
            <a href={`mailto:${d.email}`} className="text-round-blue hover:underline">
              {d.email}
            </a>
            {d.banned && <span className="rounded bg-fail/20 px-2 py-0.5 text-xs font-bold text-fail">Banned</span>}
            <span className="ml-auto text-sm text-ink-300">
              {fmtPoints(d.total_points)} points · {d.weeks} {d.weeks === 1 ? "week" : "weeks"} · {d.entries} {d.entries === 1 ? "submission" : "submissions"}
            </span>
          </div>

          <section className="flex flex-wrap items-end gap-3 rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
            <label className="block text-sm text-ink-200">
              Name
              <input className={`${input} mt-1 block w-64`} value={edit.name} maxLength={60} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
            </label>
            <label className="block text-sm text-ink-200">
              Year
              <select className={`${input} mt-1 block`} value={edit.year_group} onChange={(e) => setEdit({ ...edit, year_group: e.target.value })}>
                <option value="">–</option>
                {YEAR_GROUPS.map((y) => (
                  <option key={y.id} value={y.id}>
                    {y.label}
                  </option>
                ))}
              </select>
            </label>
            <Button size="sm" disabled={busy || !changed || edit.name.trim().length < 2} onClick={() => void save()}>
              Save
            </Button>
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => void save({ banned: !d.banned })}>
                {d.banned ? "Unban" : "Ban"}
              </Button>
              <Button size="sm" variant="danger" disabled={busy} onClick={() => setConfirm({ kind: "all" })}>
                Delete all data
              </Button>
            </div>
          </section>

          {!d.weeks_detail.length && <p className="text-sm text-ink-400">No submissions.</p>}
          {d.weeks_detail.map((w) => (
            <section key={w.id} className="space-y-2 rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="font-bold text-white">{w.title}</h2>
                <span className="text-xs text-ink-400">
                  {new Date(w.opens_at).toLocaleDateString("en-GB")} ({WEEKLY_TYPES[w.type].name})
                </span>
                <span className="text-sm text-ink-200">
                  {w.rank ? `#${w.rank} (${fmtPoints(w.points)} points)` : "not ranked"}
                </span>
                <Button size="sm" variant="ghost" className="ml-auto" disabled={busy} onClick={() => setConfirm({ kind: "week", week: w })}>
                  Remove from this week
                </Button>
              </div>
              <ul className="space-y-1">
                {w.submissions.map((x) => (
                  <li key={x.id} className="rounded bg-ink-900 px-3 py-1.5 text-xs">
                    <div className="flex flex-wrap items-center gap-3">
                      <button onClick={() => setOpenCode(openCode === x.id ? null : x.id)} className="flex flex-1 flex-wrap gap-3 text-left">
                        <span className="text-ink-400">{new Date(x.submitted_at).toLocaleString("en-GB")}</span>
                        <span className={x.passed === x.total ? "font-bold text-pass" : "text-round-yellow"}>
                          {x.status === "judged" ? `${x.passed}/${x.total} tests` : x.status}
                          {x.passed !== x.total && x.verdict ? ` (${x.verdict})` : ""}
                        </span>
                        <span className="tabular-nums text-ink-200">{measureCell(w.type, x)}</span>
                        <span className="text-ink-400">{openCode === x.id ? "hide code" : "show code"}</span>
                      </button>
                      <button className="text-ink-400 hover:text-fail" disabled={busy} onClick={() => setConfirm({ kind: "entry", id: x.id })}>
                        Remove
                      </button>
                    </div>
                    {openCode === x.id && <pre className="mt-2 overflow-x-auto rounded border border-ink-600 bg-ink-800 p-3 font-mono text-sm text-white">{x.code}</pre>}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <Modal
        open={!!confirm}
        title={confirm?.kind === "all" ? "Delete all data?" : confirm?.kind === "week" ? "Remove from this week?" : "Remove submission?"}
        onClose={() => setConfirm(null)}
        onConfirm={runConfirm}
        confirmLabel={confirm?.kind === "all" ? "Delete" : "Remove"}
        danger
        busy={busy}
      >
        {confirm?.kind === "all" && `Deletes ${d?.name} and all ${d?.entries} submissions. The email can be used again.`}
        {confirm?.kind === "week" && `Removes all of ${d?.name}'s submissions for ${confirm.week.title}.`}
        {confirm?.kind === "entry" && "This can't be undone."}
      </Modal>
    </main>
  );
}
