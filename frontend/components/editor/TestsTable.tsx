"use client";
import type { IOCase } from "@/lib/types";

export function TestsTable({ label, rows, onChange, max = 60, hint }: { label: string; rows: IOCase[]; onChange: (rows: IOCase[]) => void; max?: number; hint?: string }) {
  const set = (i: number, patch: Partial<IOCase>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const cell = "w-full resize-y rounded border border-ink-600 bg-ink-900 p-1.5 font-mono text-xs text-ink-200 focus:border-round-blue focus:outline-none";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-semibold text-white">
          {label} <span className="font-normal text-ink-400">({rows.length})</span>
        </span>
        {hint && <span className="text-xs text-ink-400">{hint}</span>}
      </div>
      <table className="w-full table-fixed border-separate border-spacing-y-1 text-xs">
        <thead className="text-left text-ink-400">
          <tr>
            <th className="w-8">#</th>
            <th>Input (stdin)</th>
            <th>Expected output</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="align-top">
              <td className="pt-1.5 text-ink-400">{i + 1}</td>
              <td className="pr-1">
                <textarea aria-label={`${label} ${i + 1} input`} rows={2} className={cell} value={r.stdin} onChange={(e) => set(i, { stdin: e.target.value })} spellCheck={false} />
              </td>
              <td className="pr-1">
                <textarea aria-label={`${label} ${i + 1} expected`} rows={2} className={cell} value={r.expected} onChange={(e) => set(i, { expected: e.target.value })} spellCheck={false} />
              </td>
              <td>
                <button onClick={() => onChange(rows.filter((_, j) => j !== i))} className="rounded px-1.5 py-1 text-ink-400 hover:bg-ink-700 hover:text-fail" aria-label={`Remove ${label} ${i + 1}`}>
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        onClick={() => onChange([...rows, { stdin: "", expected: "" }])}
        disabled={rows.length >= max}
        className="mt-1 rounded bg-ink-600 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:bg-ink-500 disabled:opacity-40"
      >
        + Add row
      </button>
    </div>
  );
}
