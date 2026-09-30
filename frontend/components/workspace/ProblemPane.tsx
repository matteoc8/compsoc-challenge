"use client";
import { InlineCountdown } from "@/components/stage/Countdown";
import { Markdown } from "@/components/ui/Markdown";
import { fmtPoints, TYPE_ACCENT } from "@/lib/format";
import type { PublicQuestion } from "@/lib/types";

export function ProblemPane({
  q,
  attempts,
  maxAttempts,
  points,
  practice = false,
}: {
  q: Pick<PublicQuestion, "round_name" | "title" | "description_md"> & Partial<PublicQuestion>;
  attempts?: number;
  maxAttempts?: number;
  points?: number | null;
  practice?: boolean;
}) {
  const accent = q.type ? TYPE_ACCENT[q.type] : "#F6B73C";
  return (
    <div className="flex h-full flex-col overflow-hidden bg-ink-800">
      <div className="flex items-center justify-between gap-3 border-b border-ink-600 px-4 py-2.5" style={{ borderTop: `4px solid ${accent}` }}>
        <div className="min-w-0">
          <div className="truncate font-stage text-xs font-extrabold uppercase tracking-wider" style={{ color: accent }}>
            {q.round_name}
          </div>
          <h1 className="truncate text-lg font-bold text-white">{q.title}</h1>
        </div>
        {!practice && <InlineCountdown />}
      </div>
      {!practice && (
        <div className="grid grid-cols-2 gap-px border-b border-ink-600 bg-ink-600 text-center text-xs">
          <div className="bg-ink-800 px-2 py-1.5">
            <div className="text-ink-400">Attempts</div>
            <div className="font-mono font-bold text-white">
              {attempts ?? 0} / {maxAttempts ?? 20}
            </div>
          </div>
          <div className="bg-ink-800 px-2 py-1.5">
            <div className="text-ink-400">{q.type === "super_fast" ? "Your score" : "Score (at close)"}</div>
            <div className="font-mono font-bold text-white">{fmtPoints(points ?? (q.type === "super_fast" ? 0 : null))}</div>
          </div>
        </div>
      )}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm leading-relaxed text-ink-200">
        {q.image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={q.image_url} alt={q.image_alt || ""} className="max-h-64 rounded-md border border-ink-600 object-contain" />
        )}
        <Markdown>{q.description_md}</Markdown>
        {q.type === "best_complexity" && q.benchmark_sizes && (
          <div className="rounded-md border border-round-green/50 bg-round-green/10 p-3 text-xs text-ink-200">
            After time is up, correct solutions are timed on inputs of{" "}
            <b className="text-white">{q.benchmark_sizes.map((n) => n.toLocaleString("en-GB")).join(", ")}</b> items. Keep the function
            signature from the starter code.
          </div>
        )}
        {q.type === "code_golf" && q.golf_rule && (
          <div className="rounded-md border border-round-blue/50 bg-round-blue/10 p-3 text-xs text-ink-200">
            <b className="text-white">How characters are counted:</b> {q.golf_rule}
          </div>
        )}
        {q.examples && q.examples.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-ink-400">Examples</h2>
            {q.examples.map((ex, i) => (
              <div key={i} className="rounded-md border border-ink-600 bg-ink-900">
                <div className="border-b border-ink-600 px-3 py-1 text-xs text-ink-400">Example {i + 1}</div>
                <div className="grid grid-cols-2 divide-x divide-ink-600">
                  <div className="p-2">
                    <div className="mb-1 text-[11px] uppercase text-ink-400">Input</div>
                    <pre className="whitespace-pre-wrap break-all font-mono text-xs text-ink-200">{ex.stdin || "(empty)"}</pre>
                  </div>
                  <div className="p-2">
                    <div className="mb-1 text-[11px] uppercase text-ink-400">Output</div>
                    <pre className="whitespace-pre-wrap break-all font-mono text-xs text-ink-200">{ex.expected}</pre>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        {!practice && (
          <ul className="space-y-0.5 text-xs text-ink-400">
            <li>
              Hidden tests: <b className="text-ink-200">{q.tests_total}</b> (you only see how many pass)
            </li>
            <li>
              Limits: <b className="text-ink-200">{q.cpu_limit_s} s</b> CPU, <b className="text-ink-200">{q.memory_mb} MB</b> per test · Python 3.8
            </li>
            <li>
              Max points: <b className="text-ink-200">{fmtPoints(q.scoring_max)}</b>
            </li>
          </ul>
        )}
      </div>
    </div>
  );
}
