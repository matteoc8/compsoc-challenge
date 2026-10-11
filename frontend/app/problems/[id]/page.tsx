"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DifficultyBadge, Examples, type FeaturedSummary } from "@/components/site/problems";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import type { IOCase } from "@/lib/types";

interface Problem extends FeaturedSummary {
  description_md: string;
  examples: IOCase[];
  has_solution: boolean;
}

export default function ProblemPage() {
  const { id } = useParams<{ id: string }>();
  const [problem, setProblem] = useState<Problem | null>(null);
  const [solution, setSolution] = useState<{ solution_code: string; solution_md: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Problem>(`/problems/${id}`)
      .then(setProblem)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load the problem"));
  }, [id]);

  // The solution is a separate request, so it's only on the page once someone asks for it.
  const reveal = async () => {
    setBusy(true);
    try {
      setSolution(await api(`/problems/${id}/solution`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load the solution");
    } finally {
      setBusy(false);
    }
  };

  if (error && !problem)
    return (
      <p className="text-ink-300">
        {error}.{" "}
        <Link href="/problems" className="text-round-blue underline">
          All problems
        </Link>
      </p>
    );
  if (!problem) return <p className="text-ink-400">Loading…</p>;

  return (
    <article className="space-y-6">
      <div>
        <Link href="/problems" className="text-sm text-ink-400 hover:text-white">
          ← All problems
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="font-stage text-4xl font-black text-white">{problem.title}</h1>
          <DifficultyBadge d={problem.difficulty} />
        </div>
        {problem.credit && <p className="mt-1 text-sm text-ink-400">{problem.credit}</p>}
      </div>
      <Markdown className="text-ink-200">{problem.description_md}</Markdown>
      <Examples examples={problem.examples} />

      {problem.has_solution && !solution && (
        <div>
          <Button variant="secondary" disabled={busy} onClick={reveal}>
            {busy ? "Loading…" : "Show solution"}
          </Button>
          {error && <p className="mt-2 text-sm text-fail">{error}</p>}
        </div>
      )}
      {problem.has_solution && solution && (
        <section className="space-y-4 rounded-lg border border-ink-600 bg-ink-800 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-stage text-xl font-black text-white">Solution</h2>
            <Button variant="ghost" size="sm" onClick={() => setSolution(null)}>
              Hide
            </Button>
          </div>
          {solution.solution_md.trim() && <Markdown className="text-ink-200">{solution.solution_md}</Markdown>}
          {solution.solution_code.trim() && (
            <pre className="overflow-x-auto rounded-md border border-ink-600 bg-ink-900 p-4 font-mono text-sm text-white">{solution.solution_code}</pre>
          )}
        </section>
      )}
    </article>
  );
}
