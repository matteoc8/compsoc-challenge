// Shared bits for the problems pages (public and admin).

import type { IOCase } from "@/lib/types";

export type Difficulty = "easy" | "medium" | "hard";

export interface FeaturedSummary {
  id: string;
  title: string;
  difficulty: Difficulty;
  credit: string | null;
  group_id: string | null;
  created_at: string;
}

export interface ProblemGroup {
  id: string;
  name: string;
  description: string;
  position: number;
}

const DIFFICULTY_STYLE: Record<Difficulty, string> = {
  easy: "bg-pass/15 text-pass",
  medium: "bg-round-yellow/15 text-round-yellow",
  hard: "bg-fail/15 text-fail",
};

export function DifficultyBadge({ d }: { d: Difficulty }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-bold capitalize ${DIFFICULTY_STYLE[d] ?? DIFFICULTY_STYLE.medium}`}>{d}</span>;
}

export function Examples({ examples }: { examples: IOCase[] }) {
  if (!examples.length) return null;
  return (
    <div className="space-y-3">
      {examples.map((e, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-2">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-ink-400">Example {i + 1} input</div>
            <pre className="overflow-x-auto rounded-md border border-ink-600 bg-ink-900 p-3 font-mono text-sm text-white">{e.stdin || " "}</pre>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-ink-400">Output</div>
            <pre className="overflow-x-auto rounded-md border border-ink-600 bg-ink-900 p-3 font-mono text-sm text-white">{e.expected || " "}</pre>
          </div>
        </div>
      ))}
    </div>
  );
}
