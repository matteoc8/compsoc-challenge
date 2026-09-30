"use client";
// Question editor: one form per question, drag to reorder, autosave with conflict detection.

import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { FullQuestion, newQuestionBody, QuestionForm, TYPE_NAMES } from "@/components/editor/QuestionForm";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { TYPE_ACCENT } from "@/lib/format";
import { useTeacher } from "@/lib/teacher";
import type { QType } from "@/lib/types";

interface Quiz {
  id: string;
  title: string;
  settings: { allow_negative_totals?: boolean; show_reasons?: boolean; sounds?: boolean };
  questions: FullQuestion[];
}

interface VerifyReport {
  ok: boolean;
  problems: string[];
  tests: { passed: boolean; status: string; actual: string; stderr: string; time_ms: number | null }[];
  examples: { passed: boolean; status: string }[];
  benchmark?: { baseline_ms: Record<string, number>; reference_ms: Record<string, number> };
}

type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict";

function body(q: FullQuestion, expected: string | null) {
  return {
    round_name: q.round_name,
    type: q.type,
    title: q.title,
    description_md: q.description_md,
    image_media_id: q.image_media_id,
    image_alt: q.image_alt,
    starter_code: q.starter_code,
    reference_solution: q.reference_solution,
    config: q.config,
    time_limit_s: q.time_limit_s,
    auto_end: q.auto_end,
    scoring: q.scoring,
    expected_updated_at: expected,
  };
}

function SortableItem({ q, active, onSelect }: { q: FullQuestion; active: boolean; onSelect: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: q.id });
  return (
    <li ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={`flex items-stretch rounded-md ${active ? "bg-ink-600" : "bg-ink-800 hover:bg-ink-700"}`}>
      <button {...attributes} {...listeners} className="cursor-grab px-2 text-ink-400 active:cursor-grabbing" aria-label={`Reorder ${q.title}`}>
        ⠿
      </button>
      <button onClick={onSelect} className="min-w-0 flex-1 py-2 pr-2 text-left">
        <div className="truncate text-xs font-bold uppercase" style={{ color: TYPE_ACCENT[q.type] }}>
          {q.round_name}
        </div>
        <div className="truncate text-sm text-white">{q.title}</div>
        <div className={`text-xs ${q.verified_at ? "text-pass" : "text-round-yellow"}`}>{q.verified_at ? "✓ verified" : "not verified"}</div>
      </button>
    </li>
  );
}

export default function EditQuizPage() {
  const me = useTeacher();
  const { id } = useParams<{ id: string }>();
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [save, setSave] = useState<SaveState>("saved");
  const [conflict, setConflict] = useState<FullQuestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<VerifyReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [title, setTitle] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saving = useRef(false);
  const pendingSave = useRef<FullQuestion | null>(null);
  // The server's updated_at for each question: the optimistic-concurrency token for autosave.
  const stamps = useRef<Record<string, string | null>>({});
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  const load = useCallback(async () => {
    const q = await api<Quiz>(`/quizzes/${id}`);
    for (const x of q.questions) stamps.current[x.id] = x.updated_at;
    setQuiz(q);
    setTitle(q.title);
    setSelected((s) => (s && q.questions.some((x) => x.id === s) ? s : q.questions[0]?.id ?? null));
  }, [id]);

  useEffect(() => {
    if (me) load().catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load the quiz"));
  }, [me, load]);

  const current = quiz?.questions.find((q) => q.id === selected) ?? null;

  const replaceQuestion = (q: FullQuestion) => {
    stamps.current[q.id] = q.updated_at;
    setQuiz((z) => (z ? { ...z, questions: z.questions.map((x) => (x.id === q.id ? q : x)) } : z));
  };

  const doSave = useCallback(async (q: FullQuestion, force = false): Promise<void> => {
    saving.current = true;
    setSave("saving");
    try {
      const saved = await api<FullQuestion>(`/questions/${q.id}`, { method: "PUT", body: body(q, force ? null : stamps.current[q.id] ?? null) });
      stamps.current[q.id] = saved.updated_at;
      // Keep the local content (the teacher may have typed more); take the server's metadata.
      setQuiz((z) =>
        z ? { ...z, questions: z.questions.map((x) => (x.id === q.id ? { ...x, updated_at: saved.updated_at, verified_at: saved.verified_at, image_url: saved.image_url } : x)) } : z,
      );
      saving.current = false;
      const next = pendingSave.current;
      if (next) {
        pendingSave.current = null;
        return doSave(next);
      }
      setSave("saved");
      setError(null);
    } catch (e) {
      saving.current = false;
      if (e instanceof ApiError && e.status === 409) {
        setConflict((e.detail as { current: FullQuestion }).current);
        setSave("conflict");
      } else {
        setSave("error");
        setError(e instanceof ApiError ? e.message : "Save failed");
      }
    }
  }, []);

  const queueSave = (q: FullQuestion) => {
    if (saving.current) pendingSave.current = q;
    else void doSave(q);
  };

  const edit = (patch: Partial<FullQuestion>) => {
    if (!current) return;
    const next = { ...current, ...patch };
    setQuiz((z) => (z ? { ...z, questions: z.questions.map((x) => (x.id === next.id ? next : x)) } : z));
    setSave("dirty");
    setReport(null);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      queueSave(next);
    }, 1200);
  };

  /** Save now (before verify / generate / switching question). */
  const flush = async () => {
    if (timer.current && current) {
      clearTimeout(timer.current);
      timer.current = null;
      await doSave(current);
    }
    while (saving.current) await new Promise((r) => setTimeout(r, 50));
  };

  // flush before leaving the question
  const select = (qid: string) => {
    void flush();
    setReport(null);
    setSelected(qid);
  };

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

  const addQuestion = (type: QType) =>
    act("add", async () => {
      const q = await api<FullQuestion>(`/quizzes/${id}/questions`, { body: newQuestionBody(type, (quiz?.questions.length ?? 0) + 1) });
      setQuiz((z) => (z ? { ...z, questions: [...z.questions, q] } : z));
      setSelected(q.id);
    });

  const onDragEnd = (e: DragEndEvent) => {
    if (!quiz || !e.over || e.active.id === e.over.id) return;
    const from = quiz.questions.findIndex((q) => q.id === e.active.id);
    const to = quiz.questions.findIndex((q) => q.id === e.over!.id);
    const questions = arrayMove(quiz.questions, from, to);
    setQuiz({ ...quiz, questions });
    void act("order", async () => {
      await api(`/quizzes/${id}/order`, { method: "PUT", body: { question_ids: questions.map((q) => q.id) } });
    });
  };

  if (!me || !quiz) return <main className="p-6 text-ink-400">{error ?? "Loading…"}</main>;

  return (
    <main className="flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-ink-600 bg-ink-800 px-4 py-2">
        <Link href="/teacher" className="text-sm text-ink-400 hover:text-white">
          ← Quizzes
        </Link>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title.trim() && title !== quiz.title && act("title", async () => void (await api(`/quizzes/${id}`, { method: "PUT", body: { title: title.trim(), settings: quiz.settings } }), setQuiz({ ...quiz, title: title.trim() })))}
          className="min-w-[240px] flex-1 rounded border border-transparent bg-transparent px-2 py-1 font-stage text-lg font-black text-white hover:border-ink-600 focus:border-round-blue focus:outline-none"
          aria-label="Quiz title"
        />
        <span className={`text-xs ${save === "saved" ? "text-ink-400" : save === "error" || save === "conflict" ? "text-fail" : "text-round-yellow"}`} role="status">
          {save === "saved" ? "All changes saved" : save === "saving" ? "Saving…" : save === "dirty" ? "Unsaved changes" : save === "conflict" ? "Conflict" : "Save failed"}
        </span>
        {(["allow_negative_totals", "show_reasons", "sounds"] as const).map((k) => (
          <label key={k} className="flex items-center gap-1.5 text-xs text-ink-300">
            <input
              type="checkbox"
              checked={k === "allow_negative_totals" ? !!quiz.settings[k] : quiz.settings[k] !== false}
              onChange={(e) => {
                const settings = { ...quiz.settings, [k]: e.target.checked };
                setQuiz({ ...quiz, settings });
                void act("settings", async () => void (await api(`/quizzes/${id}`, { method: "PUT", body: { title: quiz.title, settings } })));
              }}
            />
            {k === "allow_negative_totals" ? "Allow totals below zero" : k === "show_reasons" ? "Show point reasons on projector" : "Projector sounds"}
          </label>
        ))}
      </header>
      {error && (
        <div className="bg-fail/15 px-4 py-2 text-sm text-fail" role="alert">
          {error}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <aside className="w-64 shrink-0 overflow-y-auto border-r border-ink-600 bg-ink-900 p-3">
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={quiz.questions.map((q) => q.id)} strategy={verticalListSortingStrategy}>
              <ol className="space-y-1.5">
                {quiz.questions.map((q) => (
                  <SortableItem key={q.id} q={q} active={q.id === selected} onSelect={() => select(q.id)} />
                ))}
              </ol>
            </SortableContext>
          </DndContext>
          <div className="mt-4 space-y-1.5">
            <div className="text-xs font-semibold uppercase text-ink-400">Add a question</div>
            {(Object.keys(TYPE_NAMES) as QType[]).map((t) => (
              <button key={t} onClick={() => addQuestion(t)} disabled={busy === "add"} className="block w-full rounded bg-ink-700 px-2 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-600">
                + {TYPE_NAMES[t]}
              </button>
            ))}
          </div>
        </aside>
        <section className="min-w-0 flex-1 overflow-y-auto p-6">
          {current ? (
            <>
              <div className="mb-5 flex flex-wrap items-center gap-2">
                {current.type !== "multiple_choice" && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!!busy || !current.reference_solution.trim()}
                  onClick={() =>
                    act("gen", async () => {
                      await flush();
                      const r = await api<{ failures: { index: number; status: string; stderr: string }[]; question: FullQuestion }>(`/questions/${current.id}/generate-outputs`, { method: "POST" });
                      replaceQuestion(r.question);
                      if (r.failures.length) throw new Error(`Reference solution failed on ${r.failures.length} input(s): ${r.failures[0].status} ${r.failures[0].stderr.split("\n").slice(-2).join(" ")}`);
                    })
                  }
                >
                  {busy === "gen" ? "Generating…" : "Generate outputs from reference solution"}
                </Button>
                )}
                <Button
                  size="sm"
                  disabled={!!busy}
                  onClick={() =>
                    act("verify", async () => {
                      await flush();
                      const r = await api<VerifyReport & { question: FullQuestion }>(`/questions/${current.id}/verify`, { method: "POST" });
                      replaceQuestion(r.question);
                      setReport(r);
                    })
                  }
                >
                  {busy === "verify" ? "Testing…" : "Test (verify)"}
                </Button>
                <Button variant="secondary" size="sm" disabled={!!busy} onClick={() => act("dup", async () => {
                  const d = await api<FullQuestion>(`/questions/${current.id}/duplicate`, { method: "POST" });
                  setQuiz((z) => (z ? { ...z, questions: [...z.questions, d] } : z));
                  setSelected(d.id);
                })}>
                  Duplicate
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
                  Delete
                </Button>
                <span className={`ml-auto rounded px-2 py-1 text-xs font-bold ${current.verified_at ? "bg-pass/20 text-pass" : "bg-round-yellow/20 text-round-yellow"}`}>
                  {current.verified_at ? "Verified: ready for a game" : "Not verified: can't be used in a game yet"}
                </span>
              </div>
              {report && (
                <div className={`mb-5 rounded-md border p-3 text-sm ${report.ok ? "border-pass bg-pass/10" : "border-fail bg-fail/10"}`} role="status">
                  <div className={`font-bold ${report.ok ? "text-pass" : "text-fail"}`}>{report.ok ? (current.type === "multiple_choice" ? "Ready: every answer filled in and one marked correct." : "Reference solution passes every test.") : "Not ready yet"}</div>
                  {report.problems.map((p, i) => (
                    <div key={i} className="text-fail">
                      • {p}
                    </div>
                  ))}
                  {report.tests.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {report.tests.map((t, i) => (
                        <span key={i} title={t.passed ? `${t.time_ms} ms` : `${t.status}: ${t.actual.slice(0, 80)}${t.stderr ? " · " + t.stderr.slice(-120) : ""}`} className={`rounded px-1.5 py-0.5 font-mono text-xs ${t.passed ? "bg-pass/20 text-pass" : "bg-fail/20 text-fail"}`}>
                          {i + 1}
                        </span>
                      ))}
                    </div>
                  )}
                  {report.benchmark && (
                    <div className="mt-2 text-xs text-ink-300">
                      Benchmark (reference, baseline subtracted):{" "}
                      {Object.entries(report.benchmark.reference_ms)
                        .map(([n, ms]) => `n=${n}: ${Math.round(ms)} ms`)
                        .join(" · ")}
                    </div>
                  )}
                </div>
              )}
              <QuestionForm key={current.id} q={current} onChange={edit} />
            </>
          ) : (
            <p className="text-ink-400">Add a question to get started.</p>
          )}
        </section>
      </div>
      <Modal open={!!conflict} title="This question changed elsewhere" onClose={() => setConflict(null)}>
        <p className="mb-4">Someone (maybe you, in another tab) saved a different version.</p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              if (conflict) replaceQuestion(conflict);
              setConflict(null);
              setSave("saved");
            }}
          >
            Load their version
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              if (current) void doSave(current, true);
              setConflict(null);
            }}
          >
            Keep mine (overwrite)
          </Button>
        </div>
      </Modal>
      <Modal
        open={confirmDelete}
        title={`Delete "${current?.title}"?`}
        onClose={() => setConfirmDelete(false)}
        danger
        confirmLabel="Delete"
        onConfirm={() => {
          setConfirmDelete(false);
          if (!current) return;
          void act("delete", async () => {
            await api(`/questions/${current.id}`, { method: "DELETE" });
            setSelected(null);
            await load();
          });
        }}
      />
    </main>
  );
}
