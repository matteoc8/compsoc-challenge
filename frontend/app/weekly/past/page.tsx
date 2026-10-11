"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { weeklyType, type WeeklySummary } from "@/components/site/WeeklyProblem";
import { api, ApiError } from "@/lib/api";

export default function PastWeeksPage() {
  const [past, setPast] = useState<WeeklySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<{ past: WeeklySummary[] }>("/weekly")
      .then((w) => setPast(w.past))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, []);

  return (
    <div className="space-y-4">
      <Link href="/weekly" className="text-sm text-ink-400 hover:text-white">
        ← Problem of the week
      </Link>
      <h1 className="font-stage text-4xl font-black text-white">Past weeks</h1>
      {error && <p className="text-fail">{error}</p>}
      {!past && !error && <p className="text-ink-400">Loading…</p>}
      {past && !past.length && <p className="text-ink-400">None yet.</p>}
      {past && past.length > 0 && (
        <ul className="overflow-hidden rounded-lg ring-1 ring-ink-600">
          {past.map((p) => (
            <li key={p.id} className="border-b border-ink-700 last:border-0">
              <Link href={`/weekly/${p.id}`} className="flex flex-wrap items-center gap-3 bg-ink-800 px-4 py-3 hover:bg-ink-700">
                <span className="min-w-0 flex-1 font-semibold text-white">{p.title}</span>
                {p.credit && <span className="text-xs text-ink-400">{p.credit}</span>}
                <span className="text-xs text-ink-400">{weeklyType(p.type)}</span>
                <span className="text-xs text-ink-400">{new Date(p.closes_at).toLocaleDateString("en-GB")}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
