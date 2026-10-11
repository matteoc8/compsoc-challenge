"use client";
// The home page's live parts: this week's problem, the school leaderboard and the newest problems.

import Link from "next/link";
import { Rank } from "@/components/ui/Rank";
import { useEffect, useState } from "react";
import { DifficultyBadge, type FeaturedSummary } from "@/components/site/problems";
import { weeklyType } from "@/components/site/WeeklyProblem";
import { api } from "@/lib/api";
import { fmtPoints, timeLeft } from "@/lib/format";

interface WeekSummary {
  id: string;
  title: string;
  type: "super_fast" | "code_golf" | "best_complexity";
  closes_at: string;
}
interface WeeklyIndex {
  current: WeekSummary | null;
  past: WeekSummary[];
  next_opens_at: string | null;
}
interface Standing {
  rank: number;
  name: string;
  points: number;
}
interface SchoolRow extends Standing {
  weeks: number;
}


const card = "rounded-xl bg-ink-800 p-6 ring-1 ring-ink-600";
const heading = "font-stage text-2xl font-black text-white";

function Rows({ rows, empty, extra }: { rows: Standing[]; empty: string; extra?: (r: Standing) => string }) {
  if (!rows.length) return <p className="py-4 text-sm text-ink-400">{empty}</p>;
  return (
    <ol className="divide-y divide-ink-700">
      {rows.map((r, i) => (
        <li key={i} className="flex items-center gap-3 py-2">
          <span className="flex w-7 justify-center">
            <Rank rank={r.rank} />
          </span>
          <span className="min-w-0 flex-1 truncate font-semibold text-white">{r.name}</span>
          {extra && <span className="text-xs text-ink-400">{extra(r)}</span>}
          <span className="text-sm font-bold tabular-nums text-accent">{fmtPoints(r.points)}</span>
        </li>
      ))}
    </ol>
  );
}

export function WeeklyCard() {
  const [index, setIndex] = useState<WeeklyIndex | null>(null);
  const [top, setTop] = useState<Standing[]>([]);
  useEffect(() => {
    api<WeeklyIndex>("/weekly")
      .then((w) => {
        setIndex(w);
        if (w.current) return api<{ standings: Standing[] }>(`/weekly/${w.current.id}`).then((d) => setTop(d.standings.slice(0, 3)));
      })
      .catch(() => setIndex({ current: null, past: [], next_opens_at: null }));
  }, []);
  const cur = index?.current;
  return (
    <section className={`${card} flex flex-col lg:col-span-2`}>
      <div className="flex items-center justify-between gap-3">
        <h2 className={heading}>Problem of the week</h2>
        {cur && <span className="rounded-full bg-pass/15 px-2.5 py-0.5 text-xs font-bold text-pass">{timeLeft(cur.closes_at)}</span>}
      </div>
      {!index && <p className="mt-4 text-ink-400">Loading…</p>}
      {index && cur && (
        <>
          <h3 className="mt-3 text-xl font-semibold text-white">{cur.title}</h3>
          <p className="mt-1 text-sm text-ink-300">{weeklyType(cur.type)}</p>
          <div className="mt-4 flex-1">
            <Rows rows={top} empty="No entries yet. Be the first on the board." />
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link href="/weekly" className="rounded-lg bg-accent px-5 py-2.5 font-stage font-black text-black hover:bg-accent-light">
              Have a go →
            </Link>
            {!!index.past.length && (
              <Link href="/weekly/past" className="rounded-lg px-3 py-2.5 text-sm font-semibold text-ink-300 hover:text-white">
                {index.past.length} past week{index.past.length === 1 ? "" : "s"}
              </Link>
            )}
          </div>
        </>
      )}
      {index && !cur && (
        <p className="flex flex-1 items-center py-6 text-lg text-ink-300">No problem open right now</p>
      )}
    </section>
  );
}

export function SchoolBoardCard() {
  const [rows, setRows] = useState<SchoolRow[] | null>(null);
  useEffect(() => {
    api<{ rows: SchoolRow[] }>("/weekly/leaderboard")
      .then((d) => setRows(d.rows.slice(0, 5)))
      .catch(() => setRows([]));
  }, []);
  return (
    <section className={`${card} flex flex-col`}>
      <h2 className={heading}>School leaderboard</h2>
      <div className="mt-2 flex-1">
        {rows ? <Rows rows={rows} empty="Nobody on the board yet." extra={(r) => `${(r as SchoolRow).weeks} wk`} /> : <p className="mt-2 text-ink-400">Loading…</p>}
      </div>
      <Link href="/weekly/leaderboard" className="mt-4 text-sm font-semibold text-accent hover:underline">
        Full leaderboard →
      </Link>
    </section>
  );
}

export function LatestProblems() {
  const [problems, setProblems] = useState<FeaturedSummary[] | null>(null);
  useEffect(() => {
    api<FeaturedSummary[]>("/problems")
      .then((p) => setProblems(p.slice(0, 6)))
      .catch(() => setProblems([]));
  }, []);
  return (
    <section>
      <div className="mb-3 flex items-end justify-between gap-3">
        <h2 className={heading}>Recent problems</h2>
        <Link href="/problems" className="text-sm font-semibold text-accent hover:underline">
          All problems →
        </Link>
      </div>
      {!problems && <p className="text-ink-400">Loading…</p>}
      {problems && !problems.length && <p className={`${card} text-sm text-ink-400`}>No problems up yet. They&apos;ll appear here as they&apos;re added.</p>}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {problems?.map((p) => (
          <li key={p.id}>
            <Link href={`/problems/${p.id}`} className="flex h-full flex-col gap-3 rounded-xl bg-ink-800 p-5 ring-1 ring-ink-600 transition hover:-translate-y-0.5 hover:bg-ink-700">
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
  );
}
