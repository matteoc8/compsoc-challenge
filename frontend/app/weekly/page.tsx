"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { WeeklyProblem, type WeeklySummary } from "@/components/site/WeeklyProblem";
import { api, ApiError } from "@/lib/api";

interface Index {
  current: WeeklySummary | null;
  past: WeeklySummary[];
  next_opens_at: string | null;
}

export default function WeeklyPage() {
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Index>("/weekly")
      .then(setIndex)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, []);

  if (error) return <p className="text-fail">{error}</p>;
  if (!index) return <p className="text-ink-400">Loading…</p>;
  return (
    <div className="space-y-6">
      {index.current ? (
        <WeeklyProblem id={index.current.id} />
      ) : (
        <div className="rounded-lg bg-ink-800 p-6 ring-1 ring-ink-600">
          <h1 className="font-stage text-4xl font-black text-white">Problem of the week</h1>
          <p className="mt-2 text-ink-300">
            {index.next_opens_at
              ? `The next one opens ${new Date(index.next_opens_at).toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })}.`
              : "There's no problem running right now. Check back soon."}
          </p>
          <Link href="/weekly/leaderboard" className="mt-4 inline-block text-sm text-round-blue hover:underline">
            School leaderboard →
          </Link>
        </div>
      )}
      {index.past.length > 0 && (
        <Link href="/weekly/past" className="inline-block text-sm font-semibold text-round-blue hover:underline">
          Past weeks ({index.past.length}) →
        </Link>
      )}
    </div>
  );
}
