"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Rank } from "@/components/ui/Rank";
import { fmtPoints } from "@/lib/format";
import { YEAR_GROUPS, yearLabel, type YearGroup } from "@/lib/years";

interface Row {
  rank: number;
  name: string;
  year_group: string | null;
  points: number;
  weeks: number;
  wins: number;
}

const PERIODS = [
  { id: "week", label: "This week" },
  { id: "month", label: "This month" },
  { id: "year", label: "This year" }, // the school year, from 1 September
  { id: "all", label: "All time" },
] as const;
type Period = (typeof PERIODS)[number]["id"];

const YEARS = YEAR_GROUPS.map((y) => y.id);
const PRESETS: { id: string; label: string; years: YearGroup[] }[] = [
  { id: "all", label: "Everyone", years: [] },
  { id: "juniors", label: "Juniors", years: ["4", "5", "6"] },
  { id: "seniors", label: "Seniors", years: ["L8", "U8"] },
];

/** The years picked, in school order, from "4,5" or "juniors" (empty = everyone). */
function parseYears(raw: string | null): YearGroup[] {
  const picked = new Set<string>();
  for (const part of (raw ?? "").split(",")) {
    const preset = PRESETS.find((p) => p.id === part);
    (preset ? preset.years : YEARS.includes(part as YearGroup) ? [part] : []).forEach((y) => picked.add(y));
  }
  return YEARS.filter((y) => picked.has(y));
}

/** How the picked years go in the address: a preset's name if it is exactly one. */
function yearsParam(years: YearGroup[]): string {
  const key = years.join(",");
  return PRESETS.find((p) => p.years.join(",") === key)?.id ?? key;
}

export default function SchoolLeaderboardPage() {
  return (
    <Suspense>
      <SchoolLeaderboard />
    </Suspense>
  );
}

function SchoolLeaderboard() {
  const router = useRouter();
  const params = useSearchParams();
  const period: Period = PERIODS.find((p) => p.id === params.get("period"))?.id ?? "all";
  const years = parseYears(params.get("group"));
  const group = yearsParam(years);
  const [data, setData] = useState<{ rows: Row[]; weeks: number; period: Period; group: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setError(null);
    api<{ rows: Row[]; weeks: number; period: Period; group: string }>(`/weekly/leaderboard?period=${period}&group=${encodeURIComponent(group)}`)
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, [period, group]);
  const rows = data?.period === period && data.group === group ? data.rows : null;
  const go = (next: { period?: Period; years?: YearGroup[] }) => {
    const q = new URLSearchParams();
    const p = next.period ?? period;
    const g = yearsParam(next.years ?? years);
    if (p !== "all") q.set("period", p);
    if (g !== "all" && g) q.set("group", g);
    const qs = q.toString();
    router.replace(`/weekly/leaderboard${qs ? `?${qs.replace(/%2C/g, ",")}` : ""}`, { scroll: false });
  };
  const toggle = (y: YearGroup) => go({ years: years.includes(y) ? years.filter((x) => x !== y) : [...years, y].sort((a, b) => YEARS.indexOf(a) - YEARS.indexOf(b)) });
  const pill = (active: boolean) => `rounded-md px-3 py-1.5 font-semibold ${active ? "bg-ink-600 text-white" : "text-ink-300 hover:bg-ink-700 hover:text-white"}`;
  return (
    <div className="space-y-4">
      <Link href="/weekly" className="text-sm text-ink-400 hover:text-white">
        ← Problem of the week
      </Link>
      <div>
        <h1 className="font-stage text-4xl font-black text-white">School leaderboard</h1>
      </div>
      <div className="space-y-2">
        <nav className="flex flex-wrap gap-1 text-sm" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.id} onClick={() => go({ period: p.id })} aria-current={p.id === period ? "page" : undefined} className={pill(p.id === period)}>
              {p.label}
            </button>
          ))}
        </nav>
        <nav className="flex flex-wrap gap-1 text-sm" aria-label="Year group">
          {PRESETS.map((p) => (
            <button key={p.id} onClick={() => go({ years: p.years })} aria-current={p.id === group || (p.id === "all" && !years.length) ? "page" : undefined} className={pill(p.id === group || (p.id === "all" && !years.length))}>
              {p.label}
            </button>
          ))}
          <span className="mx-1.5 self-center text-ink-600" aria-hidden>
            |
          </span>
          {YEAR_GROUPS.map((y) => (
            <button key={y.id} onClick={() => toggle(y.id)} aria-pressed={years.includes(y.id)} className={pill(years.includes(y.id))}>
              {y.label}
            </button>
          ))}
        </nav>
      </div>
      {error && <p className="text-fail">{error}</p>}
      {!rows && !error && <p className="text-ink-400">Loading…</p>}
      {rows && (
        <div className="overflow-x-auto rounded-lg ring-1 ring-ink-600">
          <table className="w-full text-sm">
            <thead className="bg-ink-700 text-left text-xs text-ink-300">
              <tr>
                <th className="px-3 py-2">#</th>
                <th className="px-2">Name</th>
                <th className="px-2">Year</th>
                <th className="px-2">Weeks</th>
                <th className="px-2">Wins</th>
                <th className="px-3 text-right">Points</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-ink-700 bg-ink-800">
                  <td className="px-3 py-1.5">
                    <Rank rank={r.rank} />
                  </td>
                  <td className="px-2 text-white">{r.name}</td>
                  <td className="px-2 text-ink-300">{yearLabel(r.year_group)}</td>
                  <td className="px-2 tabular-nums">{r.weeks}</td>
                  <td className="px-2 tabular-nums">{r.wins}</td>
                  <td className="px-3 text-right tabular-nums text-white">{fmtPoints(r.points)}</td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={6} className="bg-ink-800 px-3 py-3 text-ink-400">
                    Nobody&apos;s on the board yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
