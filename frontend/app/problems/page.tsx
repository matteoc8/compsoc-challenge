"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { DifficultyBadge, type FeaturedSummary, type ProblemGroup } from "@/components/site/problems";
import { api, ApiError } from "@/lib/api";

interface Section {
  id: string;
  name: string;
  description: string;
  problems: FeaturedSummary[];
}

/** The admin's groups in their order, each with its problems; ungrouped problems last. */
function sections(groups: ProblemGroup[], problems: FeaturedSummary[]): Section[] {
  const known = new Set(groups.map((g) => g.id));
  const out: Section[] = groups.map((g) => ({ id: g.id, name: g.name, description: g.description, problems: problems.filter((p) => p.group_id === g.id) }));
  const rest = problems.filter((p) => !p.group_id || !known.has(p.group_id));
  if (rest.length) out.push({ id: "other", name: groups.length ? "More problems" : "", description: "", problems: rest });
  return out.filter((s) => s.problems.length);
}

export default function ProblemsPage() {
  const [data, setData] = useState<Section[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<ProblemGroup[]>("/problems/groups"), api<FeaturedSummary[]>("/problems")])
      .then(([g, p]) => setData(sections(g, p)))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load the problems"));
  }, []);

  const named = data?.filter((s) => s.name) ?? [];
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-stage text-4xl font-black text-white">Problems</h1>
        </div>
        <Link href="/problems/submit" className="rounded-md bg-ink-600 px-3 py-1.5 text-sm font-semibold text-ink-200 hover:bg-ink-500">
          Suggest a problem
        </Link>
      </div>
      {error && (
        <p className="rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </p>
      )}
      {!data && !error && <p className="text-ink-400">Loading…</p>}
      {named.length > 1 && (
        <nav className="mb-6 flex flex-wrap gap-2" aria-label="Groups">
          {named.map((s) => (
            <a key={s.id} href={`#group-${s.id}`} className="rounded-full bg-ink-800 px-3 py-1 text-sm font-semibold text-ink-200 ring-1 ring-ink-600 hover:bg-ink-700 hover:text-white">
              {s.name} <span className="text-ink-400">{s.problems.length}</span>
            </a>
          ))}
        </nav>
      )}
      <div className="space-y-8">
        {data?.map((s) => (
          <section key={s.id} id={`group-${s.id}`} className="scroll-mt-4">
            {s.name && (
              <div className="mb-3">
                <h2 className="font-stage text-2xl font-black text-white">{s.name}</h2>
                {s.description && <p className="text-sm text-ink-300">{s.description}</p>}
              </div>
            )}
            <ul className="grid gap-3 sm:grid-cols-2">
              {s.problems.map((p) => (
                <li key={p.id}>
                  <Link href={`/problems/${p.id}`} className="flex h-full flex-col gap-2 rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600 transition hover:-translate-y-0.5 hover:bg-ink-700">
                    <span className="font-semibold text-white">{p.title}</span>
                    <span className="mt-auto flex items-center gap-2">
                      <DifficultyBadge d={p.difficulty} />
                      {p.credit && <span className="truncate text-xs text-ink-400">{p.credit}</span>}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {data && !data.length && <p className="rounded-lg bg-ink-800 p-4 text-sm text-ink-400 ring-1 ring-ink-600">No problems yet. Check back soon.</p>}
      </div>
    </>
  );
}
