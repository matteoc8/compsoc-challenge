"use client";
// Problem of the week: pick a verified coding question from a quiz, set when it opens and
// closes, and see everyone's entries (with emails and code).

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { measureCell, WEEKLY_TYPES } from "@/components/site/WeeklyProblem";
import { AdminNav } from "@/components/admin/AdminNav";
import { FeatureModal } from "@/components/admin/ProblemGroups";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { fmtPoints } from "@/lib/format";
import { useAdmin } from "@/lib/admin";

interface Week {
  id: string;
  title: string;
  type: "super_fast" | "code_golf" | "best_complexity";
  opens_at: string;
  closes_at: string;
  phase: "upcoming" | "open" | "closed";
  question_id: string;
  quiz_title: string;
  verified: boolean;
  published: boolean;
  solution_published: boolean;
  credit: string | null;
  featured: boolean;
  entries: number;
  people: number;
}

interface Candidate {
  id: string;
  title: string;
  type: "code_golf" | "best_complexity";
  quiz_title: string;
  verified: boolean;
}

interface Entries extends Week {
  standings: { rank: number; name: string; email: string; passed: number | null; total: number | null; points: number; chars: number | null; class_label: string | null; time_ms: number | null; solved_after_ms: number | null }[];
  submissions: { id: number; name: string; email: string; code: string; status: string; passed: number | null; total: number | null; verdict: string | null; chars: number; class_label: string | null; submitted_at: string }[];
}

interface Form {
  id?: string;
  question_id: string;
  opens_at: string; // datetime-local value
  closes_at: string;
  published: boolean;
  solution_published: boolean;
  credit: string;
}

const pad = (n: number) => String(n).padStart(2, "0");
function toLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function blankForm(question_id = ""): Form {
  const open = new Date(); // from now; change it to schedule one for later
  open.setSeconds(0, 0);
  // weeks change over on Tuesdays: close at midnight going into the first Tuesday at least 5 days away
  const close = new Date(open.getTime() + 5 * 24 * 3600 * 1000);
  close.setHours(0, 0, 0, 0);
  close.setDate(close.getDate() + ((2 - close.getDay() + 7) % 7));
  return { question_id, opens_at: toLocal(open), closes_at: toLocal(close), published: true, solution_published: true, credit: "" };
}

const PHASE_STYLE = { upcoming: "bg-round-blue/20 text-round-blue", open: "bg-pass/20 text-pass", closed: "bg-ink-600 text-ink-300" };

export default function AdminWeeklyPage() {
  const me = useAdmin();
  const [weeks, setWeeks] = useState<Week[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [authors, setAuthors] = useState<{ author_name: string; title: string }[]>([]);
  const [form, setForm] = useState<Form | null>(null);
  const [view, setView] = useState<Entries | null>(null);
  const [openCode, setOpenCode] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Week | null>(null);
  const [featuring, setFeaturing] = useState<Week | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [w, c] = await Promise.all([api<Week[]>("/weekly-admin"), api<Candidate[]>("/weekly-admin/questions")]);
    setWeeks(w);
    setCandidates(c);
    api<{ items: { author_name: string; title: string }[] }>("/problem-submissions?status=accepted")
      .then((r) => setAuthors(r.items))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (me) load().catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, [me, load]);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveForm = () =>
    act(async () => {
      const f = form!;
      const body = { question_id: f.question_id, opens_at: new Date(f.opens_at).toISOString(), closes_at: new Date(f.closes_at).toISOString(), published: f.published, solution_published: f.solution_published, credit: f.credit };
      await api(f.id ? `/weekly-admin/${f.id}` : "/weekly-admin", { method: f.id ? "PUT" : "POST", body });
      setForm(null);
      await load();
    });

  const openEntries = (w: Week) =>
    act(async () => {
      setView(await api<Entries>(`/weekly-admin/${w.id}/entries`));
      setOpenCode(null);
    });

  if (!me) return null;
  const input = "w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none";
  const verified = candidates.filter((c) => c.verified);

  return (
    <main className="mx-auto min-h-full max-w-6xl p-6">
      <AdminNav me={me} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold text-white">Problem of the week</h1>
        <Button size="sm" disabled={busy} onClick={() => setForm(blankForm(verified[0]?.id))}>
          + New week
        </Button>
        <a href="/weekly" target="_blank" rel="noreferrer" className="text-sm text-round-blue hover:underline">
          Open the public page ↗
        </a>
        <span className="ml-auto text-xs text-ink-400">
          Write the problem as a coding question in any quiz (hidden tests, reference solution) and press Verify. Then pick it here.
        </span>
      </div>
      {error && (
        <div className="mb-4 rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="mb-4 flex items-center gap-3 rounded-md bg-pass/15 p-3 text-sm text-pass" role="status">
          {notice}
          <Link href="/admin/featured" className="font-semibold underline">
            Open Featured problems
          </Link>
          <button className="ml-auto text-ink-300 hover:text-white" onClick={() => setNotice(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      {form && (
        <section className="mb-6 space-y-3 rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
          <h2 className="font-bold text-white">{form.id ? "Edit week" : "New week"}</h2>
          {!candidates.length && (
            <p className="text-sm text-round-yellow">
              No coding questions yet. <Link href="/admin" className="underline">Create one in a quiz</Link> first.
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-3">
            <label className="block text-sm text-ink-200 md:col-span-3">
              Question
              <select className={`${input} mt-1`} value={form.question_id} onChange={(e) => setForm({ ...form, question_id: e.target.value })}>
                <option value="">Choose…</option>
                {candidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.quiz_title} › {c.title} ({WEEKLY_TYPES[c.type].name}){c.verified ? "" : " (not verified)"}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm text-ink-200">
              Opens
              <input type="datetime-local" className={`${input} mt-1`} value={form.opens_at} onChange={(e) => setForm({ ...form, opens_at: e.target.value })} />
            </label>
            <label className="block text-sm text-ink-200">
              Closes
              <input type="datetime-local" className={`${input} mt-1`} value={form.closes_at} onChange={(e) => setForm({ ...form, closes_at: e.target.value })} />
            </label>
            <div className="space-y-1 pt-5 text-sm text-ink-200">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={form.published} onChange={(e) => setForm({ ...form, published: e.target.checked })} />
                Published (visible once it opens)
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={form.solution_published} onChange={(e) => setForm({ ...form, solution_published: e.target.checked })} />
                Show the solution after it closes
              </label>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block text-sm text-ink-200">
              Submitted by <span className="text-ink-400">(optional)</span>
              <input className={`${input} mt-1 w-72`} value={form.credit} maxLength={80} placeholder="Submitted by Sam Smith" onChange={(e) => setForm({ ...form, credit: e.target.value })} />
            </label>
            {authors.length > 0 && (
              <select className={`${input} w-72`} value="" onChange={(e) => e.target.value && setForm({ ...form, credit: `Submitted by ${e.target.value}` })} aria-label="From an approved submission">
                <option value="">From an approved submission…</option>
                {authors.map((a, i) => (
                  <option key={i} value={a.author_name}>
                    {a.author_name} ({a.title})
                  </option>
                ))}
              </select>
            )}
          </div>
          <p className="text-xs text-ink-400">
            Scoring: up to 1,000 points a week. Fastest Code ranks by quickest execution on big inputs, Code Golf by shortest code; partial
            solutions get partial credit below every full solve. Weekly points add up on the school leaderboard.
          </p>
          <div className="flex gap-2">
            <Button size="sm" disabled={busy || !form.question_id} onClick={saveForm}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setForm(null)}>
              Cancel
            </Button>
          </div>
        </section>
      )}

      <div className="overflow-hidden rounded-lg ring-1 ring-ink-600">
        {weeks.map((w) => (
          <div key={w.id} className="flex flex-wrap items-center gap-3 border-b border-ink-700 bg-ink-800 px-4 py-3 last:border-0">
            <span className={`rounded px-2 py-0.5 text-xs font-bold capitalize ${PHASE_STYLE[w.phase]}`}>{w.phase}</span>
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-white">
                {w.title} <span className="text-xs font-normal text-ink-400">({WEEKLY_TYPES[w.type].name}, from {w.quiz_title})</span>
              </div>
              <div className="text-xs text-ink-400">
                {new Date(w.opens_at).toLocaleString("en-GB")} → {new Date(w.closes_at).toLocaleString("en-GB")} · {w.people} people, {w.entries} submissions
                {!w.published && <span className="ml-2 text-round-yellow">not published</span>}
                {!w.verified && <span className="ml-2 text-fail">question not verified</span>}
              </div>
            </div>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => openEntries(w)}>
              Entries
            </Button>
            {w.phase === "closed" && w.featured && <span className="text-xs text-ink-400">In Past Weekly Problems</span>}
            {w.phase === "closed" && !w.featured && (
              <Button size="sm" variant="secondary" title="Put it on the Problems page" onClick={() => setFeaturing(w)}>
                Feature on site…
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              onClick={() =>
                setForm({ id: w.id, question_id: w.question_id, opens_at: toLocal(new Date(w.opens_at)), closes_at: toLocal(new Date(w.closes_at)), published: w.published, solution_published: w.solution_published, credit: w.credit ?? "" })
              }
            >
              Edit
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(w)} aria-label={`Delete ${w.title}`}>
              ✕
            </Button>
          </div>
        ))}
        {!weeks.length && <p className="bg-ink-800 p-4 text-sm text-ink-400">No problems of the week yet.</p>}
      </div>

      {view && (
        <section className="mt-6 space-y-4 rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-white">Entries ({view.title})</h2>
            <Button size="sm" variant="ghost" onClick={() => setView(null)}>
              Close
            </Button>
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-400">
              <tr>
                <th className="py-1">#</th>
                <th>Name</th>
                <th>Email</th>
                <th>Tests</th>
                <th>Measure</th>
                <th className="text-right">Points</th>
              </tr>
            </thead>
            <tbody>
              {view.standings.map((r) => (
                <tr key={r.email} className="border-t border-ink-700">
                  <td className="py-1 tabular-nums">{r.rank}</td>
                  <td className="text-white">{r.name}</td>
                  <td>
                    <a href={`mailto:${r.email}`} className="text-round-blue hover:underline">
                      {r.email}
                    </a>
                  </td>
                  <td className="tabular-nums">
                    {r.passed}/{r.total}
                  </td>
                  <td className="tabular-nums">{measureCell(view.type, r)}</td>
                  <td className="text-right tabular-nums text-white">{fmtPoints(r.points)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3 className="text-sm font-bold text-white">All submissions</h3>
          <ul className="space-y-1">
            {view.submissions.map((e) => (
              <li key={e.id} className="rounded bg-ink-900 px-3 py-1.5 text-xs">
                <button onClick={() => setOpenCode(openCode === e.id ? null : e.id)} className="flex w-full flex-wrap gap-3 text-left">
                  <span className="text-ink-400">{new Date(e.submitted_at).toLocaleString("en-GB")}</span>
                  <span className="text-white">{e.name}</span>
                  <span className={e.passed === e.total ? "text-pass" : "text-round-yellow"}>{e.status === "judged" ? `${e.passed}/${e.total}` : e.status}</span>
                  <span className="tabular-nums">{e.chars} chars</span>
                  {e.class_label && <span>{e.class_label}</span>}
                  <span className="ml-auto text-round-blue">{openCode === e.id ? "hide code" : "code"}</span>
                </button>
                {openCode === e.id && <pre className="mt-2 overflow-x-auto rounded border border-ink-600 p-2 font-mono text-white">{e.code}</pre>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <Modal
        open={!!confirmDelete}
        title={`Delete "${confirmDelete?.title}" as a problem of the week?`}
        onClose={() => setConfirmDelete(null)}
        danger
        confirmLabel="Delete"
        onConfirm={() => {
          const w = confirmDelete!;
          setConfirmDelete(null);
          void act(async () => {
            await api(`/weekly-admin/${w.id}`, { method: "DELETE" });
            if (view?.id === w.id) setView(null);
            await load();
          });
        }}
      >
        Its {confirmDelete?.entries ?? 0} submissions and its points on the school leaderboard go too. The question stays in its quiz.
      </Modal>
      <FeatureModal open={!!featuring} onClose={() => setFeaturing(null)} path={`/questions/${featuring?.question_id}/feature`} what={`"${featuring?.title}"`} onDone={setNotice} />
    </main>
  );
}
