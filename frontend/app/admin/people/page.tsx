"use client";
// Everyone who has entered the problem of the week. Open someone to see and manage everything.

import Link from "next/link";
import { useEffect, useState } from "react";
import { AdminNav } from "@/components/admin/AdminNav";
import { api, ApiError } from "@/lib/api";
import { useAdmin } from "@/lib/admin";
import { YEAR_GROUPS, yearLabel, type Person } from "@/lib/years";

type SortKey = "name" | "year_group" | "email" | "weeks" | "entries" | "last_entry_at";
const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "year_group", label: "Year" },
  { key: "email", label: "Email" },
  { key: "weeks", label: "Weeks" },
  { key: "entries", label: "Entries" },
  { key: "last_entry_at", label: "Last entry" },
];
const YEAR_ORDER = YEAR_GROUPS.map((y) => y.id as string);

/** Sort value: years in school order, missing values always last. */
function sortValue(p: Person, key: SortKey): string | number | null {
  if (key === "year_group") return p.year_group ? YEAR_ORDER.indexOf(p.year_group) : null;
  if (key === "name" || key === "email") return p[key].toLowerCase();
  return p[key];
}

export default function AdminPeoplePage() {
  const me = useAdmin();
  const [people, setPeople] = useState<Person[] | null>(null);
  const [search, setSearch] = useState("");
  const [year, setYear] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "name", dir: 1 });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    api<Person[]>("/weekly-admin/people")
      .then(setPeople)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, [me]);

  if (!me) return null;
  const q = search.trim().toLowerCase();
  const shown = (people ?? [])
    .filter((p) => (!q || p.name.toLowerCase().includes(q) || p.email.includes(q)) && (!year || p.year_group === year))
    .sort((a, b) => {
      const x = sortValue(a, sort.key);
      const y = sortValue(b, sort.key);
      if (x === y) return a.name.localeCompare(b.name);
      if (x === null) return 1;
      if (y === null) return -1;
      return (x < y ? -1 : 1) * sort.dir;
    });
  // numbers and dates start biggest/newest first; text A to Z
  const sortBy = (key: SortKey) => setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: ["weeks", "entries", "last_entry_at"].includes(key) ? -1 : 1 }));
  const input = "rounded-md border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none";

  return (
    <main className="mx-auto min-h-full max-w-6xl p-6">
      <AdminNav me={me} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold text-white">People</h1>
        {people && <span className="text-sm text-ink-400">{people.length}</span>}
        <select className={`${input} ml-auto`} value={year} onChange={(e) => setYear(e.target.value)} aria-label="Year group">
          <option value="">All years</option>
          {YEAR_GROUPS.map((y) => (
            <option key={y.id} value={y.id}>
              {y.label}
            </option>
          ))}
        </select>
        <input className={`${input} w-64`} placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search people" />
      </div>
      {error && (
        <div className="mb-4 rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </div>
      )}
      {!people && !error && <p className="text-ink-400">Loading…</p>}
      {people && (
        <div className="overflow-x-auto rounded-lg ring-1 ring-ink-600">
          <table className="w-full text-sm">
            <thead className="bg-ink-700 text-left text-xs text-ink-300">
              <tr>
                {COLUMNS.map((c, i) => (
                  <th key={c.key} className={i === 0 ? "px-3 py-2" : "px-2"} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
                    <button onClick={() => sortBy(c.key)} className={`flex items-center gap-1 hover:text-white ${sort.key === c.key ? "text-white" : ""}`}>
                      {c.label}
                      <span className="w-2 text-[10px]">{sort.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : ""}</span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.email} className={`border-t border-ink-700 ${p.banned ? "bg-fail/10" : "bg-ink-800"}`}>
                  <td className="px-3 py-1.5">
                    <Link href={`/admin/people/person?email=${encodeURIComponent(p.email)}`} className={`hover:underline ${p.banned ? "text-ink-400 line-through" : "text-white"}`}>
                      {p.name}
                    </Link>
                    {p.banned && <span className="ml-2 text-xs text-fail">banned</span>}
                  </td>
                  <td className="px-2 text-ink-300">{yearLabel(p.year_group)}</td>
                  <td className="px-2 text-ink-300">{p.email}</td>
                  <td className="px-2 tabular-nums">{p.weeks}</td>
                  <td className="px-2 tabular-nums">{p.entries}</td>
                  <td className="px-3 text-ink-300">{p.last_entry_at ? new Date(p.last_entry_at).toLocaleDateString("en-GB") : "–"}</td>
                </tr>
              ))}
              {!shown.length && (
                <tr>
                  <td colSpan={6} className="bg-ink-800 px-3 py-3 text-ink-400">
                    {people.length ? "No matches." : "Nobody has entered yet."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
