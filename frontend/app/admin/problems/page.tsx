"use client";
// The submitted-problems queue: review what people sent in from the public site.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CODING_TYPES, TYPE_NAMES } from "@/components/editor/QuestionForm";
import { Examples } from "@/components/site/problems";
import { EmailReply } from "@/components/admin/EmailReply";
import { AdminNav } from "@/components/admin/AdminNav";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { useAdmin } from "@/lib/admin";
import type { IOCase, QType } from "@/lib/types";

type Status = "pending" | "accepted" | "rejected";

interface Submitted {
  id: string;
  author_name: string;
  intended_use?: "challenge" | "weekly" | "either";
  email: string | null;
  title: string;
  description_md: string;
  examples: IOCase[];
  solution: string;
  notes: string;
  status: Status;
  teacher_note: string | null;
  created_at: string;
  reviewed_at: string | null;
  emailed_at: string | null;
}

const TABS: [Status, string][] = [
  ["pending", "To review"],
  ["accepted", "Accepted"],
  ["rejected", "Rejected"],
];

const USE_LABEL = { challenge: "CompSoc Challenge", weekly: "Weekly problem", either: "Either" };

export default function ProblemQueuePage() {
  const me = useAdmin();
  const router = useRouter();
  const [tab, setTab] = useState<Status>("pending");
  const [items, setItems] = useState<Submitted[]>([]);
  const [counts, setCounts] = useState<Record<Status, number>>({ pending: 0, accepted: 0, rejected: 0 });
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toQuiz, setToQuiz] = useState<{ quizzes: { id: string; title: string }[]; quiz_id: string; type: QType } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [emailing, setEmailing] = useState(false);

  const load = useCallback(async () => {
    const r = await api<{ items: Submitted[]; counts: Record<Status, number> }>(`/problem-submissions?status=${tab}`);
    setItems(r.items);
    setCounts(r.counts);
    setSelected((s) => (s && r.items.some((x) => x.id === s) ? s : r.items[0]?.id ?? null));
  }, [tab]);

  useEffect(() => {
    if (me) load().catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load the queue"));
  }, [me, load]);

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const current = items.find((x) => x.id === selected) ?? null;
  const review = (status: Status) =>
    act(status, async () => {
      await api(`/problem-submissions/${current!.id}`, { method: "PUT", body: { status, teacher_note: current!.teacher_note } });
      await load();
    });

  if (!me) return null;
  return (
    <main className="mx-auto min-h-full max-w-6xl p-6">
      <AdminNav me={me} pending={counts.pending} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h1 className="mr-4 text-lg font-bold text-white">Submitted problems</h1>
        {TABS.map(([s, label]) => (
          <button key={s} onClick={() => setTab(s)} className={`rounded-md px-3 py-1.5 text-sm font-semibold ${tab === s ? "bg-round-blue text-white" : "bg-ink-700 text-ink-300 hover:bg-ink-600"}`}>
            {label} <span className="opacity-70">{counts[s]}</span>
          </button>
        ))}
      </div>
      {error && (
        <div className="mb-4 rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-[280px_1fr]">
        <ul className="space-y-1.5">
          {items.map((x) => (
            <li key={x.id}>
              <button onClick={() => setSelected(x.id)} className={`w-full rounded-md px-3 py-2 text-left ${x.id === selected ? "bg-ink-600" : "bg-ink-800 hover:bg-ink-700"}`}>
                <div className="truncate text-sm font-semibold text-white">{x.title}</div>
                <div className="text-xs text-ink-400">
                  {x.author_name} · {new Date(x.created_at).toLocaleDateString("en-GB")}
                </div>
              </button>
            </li>
          ))}
          {!items.length && <li className="rounded-md bg-ink-800 p-3 text-sm text-ink-400">{tab === "pending" ? "Nothing waiting. All caught up." : "None yet."}</li>}
        </ul>
        {current && (
          <article className="space-y-5 rounded-lg bg-ink-800 p-5 ring-1 ring-ink-600">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="font-stage text-2xl font-black text-white">{current.title}</h2>
                <p className="mt-1 text-sm text-ink-200">
                  Preferred problem use: <span className="font-semibold text-white">{USE_LABEL[current.intended_use ?? "either"]}</span>
                </p>
                <p className="text-sm text-ink-400">
                  From {current.author_name}
                  {current.email && (
                    <>
                      {" "}
                      (<a href={`mailto:${current.email}`} className="text-round-blue hover:underline">{current.email}</a>)
                    </>
                  )}{" "}
                  on {new Date(current.created_at).toLocaleString("en-GB")}
                  {current.emailed_at && <span className="ml-2 rounded bg-pass/15 px-1.5 text-xs font-bold text-pass">replied {new Date(current.emailed_at).toLocaleDateString("en-GB")}</span>}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="success"
                  disabled={!!busy}
                  title="Accept it and open it as an unpublished featured problem"
                  onClick={() =>
                    act("feature", async () => {
                      const f = await api<{ id: string }>(`/problem-submissions/${current.id}/feature`, { method: "POST" });
                      router.push(`/admin/featured?id=${f.id}`);
                    })
                  }
                >
                  Feature it
                </Button>
                <Button
                  size="sm"
                  disabled={!!busy}
                  onClick={() =>
                    act("quizzes", async () => {
                      const quizzes = await api<{ id: string; title: string }[]>("/quizzes");
                      if (!quizzes.length) throw new Error("Create a quiz first");
                      setToQuiz({ quizzes, quiz_id: quizzes[0].id, type: "super_fast" });
                    })
                  }
                >
                  Add to a quiz…
                </Button>
                {current.email && (
                  <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => setEmailing(true)}>
                    Email them…
                  </Button>
                )}
                {current.status !== "rejected" && (
                  <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => review("rejected")}>
                    Reject
                  </Button>
                )}
                {current.status !== "pending" && (
                  <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => review("pending")}>
                    Back to review
                  </Button>
                )}
                <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => setConfirmDelete(true)} aria-label="Delete">
                  ✕
                </Button>
              </div>
            </div>
            <Markdown className="text-ink-200">{current.description_md}</Markdown>
            <Examples examples={current.examples} />
            {current.solution.trim() && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase text-ink-400">Their solution</div>
                <pre className="overflow-x-auto rounded-md border border-ink-600 bg-ink-900 p-3 font-mono text-sm text-white">{current.solution}</pre>
              </div>
            )}
            {current.notes.trim() && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase text-ink-400">Notes</div>
                <p className="whitespace-pre-wrap text-sm text-ink-200">{current.notes}</p>
              </div>
            )}
            <label className="block text-xs font-semibold uppercase text-ink-400">
              Your note <span className="font-normal normal-case">(private, saved when you accept, reject or move it)</span>
              <input
                value={current.teacher_note ?? ""}
                maxLength={500}
                onChange={(e) => setItems(items.map((x) => (x.id === current.id ? { ...x, teacher_note: e.target.value } : x)))}
                className="mt-1 w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm normal-case text-white focus:border-round-blue focus:outline-none"
              />
            </label>
          </article>
        )}
      </div>

      {emailing && current && <EmailReply problem={current} onClose={() => setEmailing(false)} onSent={() => void load()} />}
      <Modal
        open={!!toQuiz}
        title="Add to a quiz"
        onClose={() => setToQuiz(null)}
        confirmLabel="Add question"
        busy={busy === "to-quiz"}
        onConfirm={() =>
          act("to-quiz", async () => {
            const r = await api<{ quiz_id: string }>(`/problem-submissions/${current!.id}/to-quiz`, { body: { quiz_id: toQuiz!.quiz_id, type: toQuiz!.type } });
            setToQuiz(null);
            router.push(`/admin/quizzes/${r.quiz_id}/edit`);
          })
        }
      >
        {toQuiz && (
          <div className="space-y-3">
            <label className="block text-sm">
              Quiz
              <select value={toQuiz.quiz_id} onChange={(e) => setToQuiz({ ...toQuiz, quiz_id: e.target.value })} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-white">
                {toQuiz.quizzes.map((q) => (
                  <option key={q.id} value={q.id}>
                    {q.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Round type
              <select value={toQuiz.type} onChange={(e) => setToQuiz({ ...toQuiz, type: e.target.value as QType })} className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-white">
                {CODING_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {TYPE_NAMES[t]}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-xs text-ink-400">It&apos;s added at the end, unverified. Add hidden tests and check the reference solution before using it in a game.</p>
          </div>
        )}
      </Modal>
      <Modal
        open={confirmDelete}
        title={`Delete "${current?.title}"?`}
        onClose={() => setConfirmDelete(false)}
        danger
        confirmLabel="Delete"
        onConfirm={() => {
          setConfirmDelete(false);
          void act("delete", async () => {
            await api(`/problem-submissions/${current!.id}`, { method: "DELETE" });
            await load();
          });
        }}
      >
        This can&apos;t be undone.
      </Modal>
    </main>
  );
}
