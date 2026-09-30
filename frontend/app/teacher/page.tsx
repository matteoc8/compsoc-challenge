"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { logout, useTeacher } from "@/lib/teacher";

interface QuizSummary {
  id: string;
  title: string;
  question_count: number;
  all_verified: boolean;
  updated_at: string;
}
interface GameSummary {
  id: string;
  quiz_title: string;
  join_code: string;
  state: string;
  created_at: string;
}

export default function TeacherHome() {
  const me = useTeacher();
  const router = useRouter();
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  const [games, setGames] = useState<GameSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<QuizSummary | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [q, g] = await Promise.all([api<QuizSummary[]>("/quizzes"), api<GameSummary[]>("/games")]);
      setQuizzes(q);
      setGames(g);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load");
    }
  }, []);

  useEffect(() => {
    if (me) void load();
  }, [me, load]);

  const run = async (label: string, fn: () => Promise<void>) => {
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

  const verifyAll = (quiz: QuizSummary) =>
    run(`verify-${quiz.id}`, async () => {
      const full = await api<{ questions: { id: string; title: string }[] }>(`/quizzes/${quiz.id}`);
      const failed: string[] = [];
      for (const q of full.questions) {
        const r = await api<{ ok: boolean; problems: string[] }>(`/questions/${q.id}/verify`, { method: "POST" });
        if (!r.ok) failed.push(`${q.title}: ${r.problems.join(" ")}`);
      }
      await load();
      if (failed.length) throw new Error("Not verified: " + failed.join(" | "));
    });

  const startGame = (quiz: QuizSummary) =>
    run(`start-${quiz.id}`, async () => {
      const g = await api<{ id: string }>("/games", { body: { quiz_id: quiz.id } });
      router.push(`/teacher/games/${g.id}`);
    });

  if (!me) return null;
  return (
    <main className="mx-auto min-h-full max-w-5xl p-6">
      <header className="mb-8 flex items-center justify-between">
        <h1 className="font-stage text-3xl font-black text-white">CompSoc Challenge</h1>
        <div className="flex items-center gap-3 text-sm text-ink-400">
          {me.username}
          <Button variant="ghost" size="sm" onClick={logout}>
            Log out
          </Button>
        </div>
      </header>
      {error && (
        <div className="mb-4 rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </div>
      )}

      <section className="mb-10">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-white">Quizzes</h2>
          <div className="flex gap-2">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (!newTitle.trim()) return;
                void run("create", async () => {
                  const q = await api<QuizSummary>("/quizzes", { body: { title: newTitle.trim() } });
                  setNewTitle("");
                  router.push(`/teacher/quizzes/${q.id}/edit`);
                });
              }}
            >
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="New quiz title"
                maxLength={120}
                className="rounded-md border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none"
              />
              <Button size="sm" disabled={!newTitle.trim() || busy === "create"}>
                Create
              </Button>
            </form>
            <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()} disabled={busy === "import"}>
              Import .zip
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".zip,application/zip"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                const form = new FormData();
                form.append("file", f);
                void run("import", async () => {
                  await api("/quizzes/import", { form, method: "POST" });
                  await load();
                });
              }}
            />
          </div>
        </div>
        <div className="overflow-hidden rounded-lg ring-1 ring-ink-600">
          {quizzes.map((q) => (
            <div key={q.id} className="flex flex-wrap items-center gap-3 border-b border-ink-700 bg-ink-800 px-4 py-3 last:border-0">
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-white">{q.title}</div>
                <div className="text-xs text-ink-400">
                  {q.question_count} question{q.question_count === 1 ? "" : "s"} ·{" "}
                  {q.all_verified ? <span className="text-pass">all verified</span> : <span className="text-round-yellow">needs verifying</span>}
                </div>
              </div>
              <Link href={`/teacher/quizzes/${q.id}/edit`} className="rounded-md bg-ink-600 px-3 py-1.5 text-xs font-semibold text-ink-200 hover:bg-ink-500">
                Edit
              </Link>
              <a href={`/api/quizzes/${q.id}/export.zip`} className="rounded-md bg-ink-600 px-3 py-1.5 text-xs font-semibold text-ink-200 hover:bg-ink-500">
                Export
              </a>
              <Button size="sm" variant="secondary" onClick={() => verifyAll(q)} disabled={!!busy}>
                {busy === `verify-${q.id}` ? "Verifying…" : "Verify all"}
              </Button>
              <Button size="sm" variant="success" onClick={() => startGame(q)} disabled={!q.all_verified || !!busy} title={q.all_verified ? "" : "Verify every question first"}>
                {busy === `start-${q.id}` ? "Starting…" : "New game"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(q)} aria-label={`Delete ${q.title}`}>
                ✕
              </Button>
            </div>
          ))}
          {!quizzes.length && <p className="bg-ink-800 p-4 text-sm text-ink-400">No quizzes yet.</p>}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-bold text-white">Games</h2>
        <div className="overflow-hidden rounded-lg ring-1 ring-ink-600">
          {games.map((g) => (
            <Link key={g.id} href={`/teacher/games/${g.id}`} className="flex items-center gap-4 border-b border-ink-700 bg-ink-800 px-4 py-3 last:border-0 hover:bg-ink-700">
              <span className="font-mono text-lg font-bold text-white">{g.join_code}</span>
              <span className="flex-1 text-sm text-ink-200">{g.quiz_title}</span>
              <span className={`rounded px-2 py-0.5 text-xs font-bold ${g.state === "finished" ? "bg-ink-600 text-ink-300" : "bg-round-green/20 text-pass"}`}>{g.state}</span>
              <span className="text-xs text-ink-400">{new Date(g.created_at).toLocaleString("en-GB")}</span>
            </Link>
          ))}
          {!games.length && <p className="bg-ink-800 p-4 text-sm text-ink-400">No games yet. Verify a quiz, then start a new game.</p>}
        </div>
      </section>

      <Modal
        open={!!confirmDelete}
        title={`Delete "${confirmDelete?.title}"?`}
        onClose={() => setConfirmDelete(null)}
        danger
        confirmLabel="Delete"
        onConfirm={() => {
          const q = confirmDelete!;
          setConfirmDelete(null);
          void run("delete", async () => {
            await api(`/quizzes/${q.id}`, { method: "DELETE" });
            await load();
          });
        }}
      >
        This can&apos;t be undone. Export it first if you might want it back.
      </Modal>
    </main>
  );
}
