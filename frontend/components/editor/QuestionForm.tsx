"use client";
import dynamic from "next/dynamic";
import { Markdown } from "@/components/ui/Markdown";
import type { IOCase, QType } from "@/lib/types";
import { ImageDropZone } from "./ImageDropZone";
import { TestsTable } from "./TestsTable";

const CodeEditor = dynamic(() => import("@/components/workspace/CodeEditor"), { ssr: false, loading: () => <div className="h-40 rounded bg-[#1e1e1e]" /> });

export interface FullQuestion {
  id: string;
  position: number;
  round_name: string;
  type: QType;
  title: string;
  description_md: string;
  image_media_id: string | null;
  image_url: string | null;
  image_alt: string | null;
  starter_code: string;
  reference_solution: string;
  config: {
    examples: IOCase[];
    tests: IOCase[];
    cpu_limit_s: number;
    memory_mb: number;
    harness?: string | null;
    benchmark?: { generator: string; sizes: number[]; repeats: number; cpu_limit_s: number; floor_ms: number } | null;
    options?: { text: string }[];
    correct?: number[];
  };
  time_limit_s: number;
  auto_end: { all_passed?: boolean; after_n_passed?: number | null };
  scoring: Record<string, unknown> & { mode: string };
  verified_at: string | null;
  updated_at: string | null;
}

export const TYPE_NAMES: Record<QType, string> = {
  multiple_choice: "Multiple choice",
  super_fast: "Super Fast Round",
  code_golf: "Code Golf",
  best_complexity: "Best Time Complexity",
};

export const DEFAULT_HARNESS = `import sys as _sys
_data = _sys.stdin.read().split()
print(solve([int(x) for x in _data]))
`;

export const DEFAULT_GENERATOR = `def gen(n, rng):
    # return the arguments for solve(...) as a tuple
    return ([rng.randint(-1000, 1000) for _ in range(n)],)
`;

export function defaultScoring(type: QType) {
  if (type === "multiple_choice") return { mode: "timed", max: 1000 };
  if (type === "super_fast") return { mode: "ranked", points: [4000, 3000, 2000] };
  return { mode: "closest", max: 4000, min_share: 0.5 };
}

const BLANK_OPTIONS = () => [{ text: "" }, { text: "" }, { text: "" }, { text: "" }];

/** Config and time limit that suit a type (used when creating or switching type). */
export function typeDefaults(type: QType, cfg?: FullQuestion["config"]): Pick<FullQuestion, "config" | "time_limit_s"> {
  if (type === "multiple_choice")
    return {
      time_limit_s: 20,
      config: { examples: [], tests: [], cpu_limit_s: 2, memory_mb: 128, options: cfg?.options?.length ? cfg.options : BLANK_OPTIONS(), correct: cfg?.correct ?? [] },
    };
  const base = { examples: cfg?.examples ?? [], tests: cfg?.tests ?? [], cpu_limit_s: cfg?.cpu_limit_s ?? 2, memory_mb: cfg?.memory_mb ?? 128 };
  const time_limit_s = type === "super_fast" ? 180 : 240;
  if (type === "best_complexity")
    return {
      time_limit_s,
      config: {
        ...base,
        harness: cfg?.harness || DEFAULT_HARNESS,
        benchmark: cfg?.benchmark ?? { generator: DEFAULT_GENERATOR, sizes: [500, 2000, 8000], repeats: 3, cpu_limit_s: 5, floor_ms: 20 },
      },
    };
  return { time_limit_s, config: base };
}

export function newQuestionBody(type: QType, n: number) {
  const mcq = type === "multiple_choice";
  return {
    round_name: mcq ? `Question ${n}` : `Round ${n}: ${TYPE_NAMES[type]}`,
    type,
    title: mcq ? "Your question?" : "New challenge",
    description_md: mcq ? "" : "Describe the problem here.",
    starter_code: type === "best_complexity" ? "def solve(nums):\n    return 0\n" : "",
    reference_solution: "",
    ...typeDefaults(type),
    auto_end: {},
    scoring: defaultScoring(type),
  };
}

const MODES: Record<QType, [string, string][]> = {
  multiple_choice: [
    ["timed", "Faster correct answers score more (default)"],
    ["flat", "Same points for every correct answer"],
  ],
  super_fast: [
    ["ranked", "First teams to solve it score (default)"],
    ["speed_weighted", "Speed-weighted, partial solutions count"],
    ["flat", "Same points for every full pass"],
  ],
  code_golf: [
    ["closest", "Closest to the shortest (default)"],
    ["flat", "Flat"],
    ["ranked", "Ranked by characters"],
  ],
  best_complexity: [
    ["closest", "Closest to the fastest (default)"],
    ["flat", "Flat"],
    ["ranked", "Ranked by runtime"],
  ],
};

const inputCls = "w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-semibold text-white">
        {label} {hint && <span className="font-normal text-ink-400">· {hint}</span>}
      </span>
      {children}
    </label>
  );
}

function num(v: string, fallback: number) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function QuestionForm({ q, onChange }: { q: FullQuestion; onChange: (patch: Partial<FullQuestion>) => void }) {
  const cfg = q.config;
  const setCfg = (patch: Partial<FullQuestion["config"]>) => onChange({ config: { ...cfg, ...patch } });
  const setScoring = (patch: Record<string, unknown>) => onChange({ scoring: { ...q.scoring, ...patch } as FullQuestion["scoring"] });
  const mcq = q.type === "multiple_choice";
  const presets = mcq ? [10, 20, 30, 60] : [180, 240, 300, 360];
  const [minT, maxT] = mcq ? [5, 240] : [60, 900];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Round name" hint="shown on the intro card, ≤ 60 chars">
          <input className={inputCls} value={q.round_name} maxLength={60} onChange={(e) => onChange({ round_name: e.target.value })} />
        </Field>
        <Field label="Question type">
          <select
            className={inputCls}
            value={q.type}
            onChange={(e) => {
              const type = e.target.value as QType;
              onChange({ type, scoring: defaultScoring(type) as FullQuestion["scoring"], auto_end: {}, ...typeDefaults(type, cfg) });
            }}
          >
            {(Object.keys(TYPE_NAMES) as QType[]).map((t) => (
              <option key={t} value={t}>
                {TYPE_NAMES[t]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={mcq ? "Question" : "Title"} hint={mcq ? "shown on the projector and every team's screen, ≤ 120 chars" : undefined}>
        <input className={inputCls} value={q.title} maxLength={120} onChange={(e) => onChange({ title: e.target.value })} />
      </Field>
      {mcq && <McqAnswers q={q} onChange={onChange} />}
      <div className={`grid gap-4 md:grid-cols-2 ${mcq ? "hidden" : ""}`}>
        <Field label="Description" hint="Markdown">
          <textarea className={`${inputCls} min-h-[200px] font-mono text-xs`} value={q.description_md} onChange={(e) => onChange({ description_md: e.target.value })} />
        </Field>
        <div>
          <span className="mb-1 block text-sm font-semibold text-white">Preview</span>
          <div className="min-h-[200px] rounded border border-ink-600 bg-ink-800 p-3 text-sm text-ink-200">
            <Markdown>{q.description_md}</Markdown>
          </div>
        </div>
      </div>
      <div>
        <span className="mb-1 block text-sm font-semibold text-white">Image</span>
        <ImageDropZone url={q.image_url} alt={q.image_alt} onChange={(patch) => onChange(patch)} />
      </div>
      {!mcq && (
        <>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <span className="mb-1 block text-sm font-semibold text-white">Starter code</span>
          <div className="h-56 overflow-hidden rounded border border-ink-600">
            <CodeEditor value={q.starter_code} onChange={(v) => onChange({ starter_code: v })} ariaLabel="Starter code" />
          </div>
        </div>
        <div>
          <span className="mb-1 block text-sm font-semibold text-white">
            Reference solution <span className="font-normal text-ink-400">· never sent to teams</span>
          </span>
          <div className="h-56 overflow-hidden rounded border border-ink-600">
            <CodeEditor value={q.reference_solution} onChange={(v) => onChange({ reference_solution: v })} ariaLabel="Reference solution" />
          </div>
        </div>
      </div>
      {q.type === "best_complexity" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <span className="mb-1 block text-sm font-semibold text-white">
              I/O harness <span className="font-normal text-ink-400">· appended after the team&apos;s code: reads stdin, calls solve, prints</span>
            </span>
            <div className="h-40 overflow-hidden rounded border border-ink-600">
              <CodeEditor value={cfg.harness ?? ""} onChange={(v) => setCfg({ harness: v })} ariaLabel="Harness" lint={false} />
            </div>
          </div>
          <div>
            <span className="mb-1 block text-sm font-semibold text-white">
              Benchmark generator <span className="font-normal text-ink-400">· gen(n, rng) returns solve&apos;s arguments</span>
            </span>
            <div className="h-40 overflow-hidden rounded border border-ink-600">
              <CodeEditor
                value={cfg.benchmark?.generator ?? ""}
                onChange={(v) => setCfg({ benchmark: { ...(cfg.benchmark ?? { sizes: [500, 2000, 8000], repeats: 3, cpu_limit_s: 5, floor_ms: 20 }), generator: v } })}
                ariaLabel="Benchmark generator"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 lg:col-span-2 lg:grid-cols-4">
            <Field label="Sizes" hint="comma-separated">
              <input
                className={inputCls}
                defaultValue={(cfg.benchmark?.sizes ?? []).join(", ")}
                onBlur={(e) => {
                  const sizes = e.target.value
                    .split(",")
                    .map((x) => parseInt(x.trim(), 10))
                    .filter((n) => n > 0);
                  if (cfg.benchmark) setCfg({ benchmark: { ...cfg.benchmark, sizes } });
                }}
              />
            </Field>
            <Field label="Repeats">
              <input type="number" min={1} max={5} className={inputCls} value={cfg.benchmark?.repeats ?? 3} onChange={(e) => cfg.benchmark && setCfg({ benchmark: { ...cfg.benchmark, repeats: num(e.target.value, 3) } })} />
            </Field>
            <Field label="CPU limit (s)" hint="per run">
              <input type="number" min={1} max={15} step={0.5} className={inputCls} value={cfg.benchmark?.cpu_limit_s ?? 5} onChange={(e) => cfg.benchmark && setCfg({ benchmark: { ...cfg.benchmark, cpu_limit_s: num(e.target.value, 5) } })} />
            </Field>
            <Field label="Floor (ms)" hint="faster counts as equal">
              <input type="number" min={0} max={1000} className={inputCls} value={cfg.benchmark?.floor_ms ?? 20} onChange={(e) => cfg.benchmark && setCfg({ benchmark: { ...cfg.benchmark, floor_ms: num(e.target.value, 20) } })} />
            </Field>
          </div>
        </div>
      )}
      <TestsTable label="Visible examples" rows={cfg.examples} onChange={(examples) => setCfg({ examples })} max={10} hint="shown to teams and used by Run" />
      <TestsTable
        label="Hidden tests"
        rows={cfg.tests}
        onChange={(tests) => setCfg({ tests })}
        hint={q.type === "code_golf" ? "at least 8, include edge cases and 2–3 random inputs" : "differ from the examples; include edge cases"}
      />
        </>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Time limit">
          <div className="flex flex-wrap gap-1.5">
            {presets.map((s) => (
              <button key={s} onClick={() => onChange({ time_limit_s: s })} className={`rounded px-2.5 py-1 text-xs font-bold ${q.time_limit_s === s ? "bg-round-blue text-white" : "bg-ink-600 text-ink-200"}`}>
                {mcq ? `${s} s` : `${s / 60} min`}
              </button>
            ))}
            <input
              type="number"
              min={minT}
              max={maxT}
              aria-label="Custom time limit in seconds"
              className="w-20 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-xs text-white"
              value={q.time_limit_s}
              onChange={(e) => onChange({ time_limit_s: Math.round(num(e.target.value, 240)) })}
            />
            <span className="self-center text-xs text-ink-400">s</span>
          </div>
        </Field>
        {!mcq && (
          <>
        <Field label="CPU limit per test (s)">
          <input type="number" min={0.5} max={10} step={0.5} className={inputCls} value={cfg.cpu_limit_s} onChange={(e) => setCfg({ cpu_limit_s: num(e.target.value, 2) })} />
        </Field>
        <Field label="Memory (MB)">
          <input type="number" min={16} max={512} className={inputCls} value={cfg.memory_mb} onChange={(e) => setCfg({ memory_mb: Math.round(num(e.target.value, 128)) })} />
        </Field>
          </>
        )}
      </div>
      {q.type === "super_fast" && q.scoring.mode === "ranked" && (
        <p className="rounded-md bg-round-red/10 p-3 text-sm text-ink-200">
          Only the first {((q.scoring.points as number[]) ?? []).length} teams to pass every hidden test score, in order. The round ends automatically as soon
          as the last scoring place is taken (or when every team has solved it). The intro card tells teams this.
        </p>
      )}
      {q.type === "super_fast" && q.scoring.mode !== "ranked" && (
        <Field label="Auto-end">
          <select
            className={inputCls}
            value={q.auto_end.all_passed ? "all" : q.auto_end.after_n_passed ? "n" : "none"}
            onChange={(e) => onChange({ auto_end: e.target.value === "all" ? { all_passed: true } : e.target.value === "n" ? { after_n_passed: q.auto_end.after_n_passed || 3 } : {} })}
          >
            <option value="none">Run the full time</option>
            <option value="all">End once every team has a full pass</option>
            <option value="n">End once N teams have a full pass</option>
          </select>
          {q.auto_end.after_n_passed != null && !q.auto_end.all_passed && (
            <input type="number" min={1} max={100} className={`${inputCls} mt-2 w-24`} value={q.auto_end.after_n_passed} onChange={(e) => onChange({ auto_end: { after_n_passed: Math.max(1, Math.round(num(e.target.value, 3))) } })} />
          )}
        </Field>
      )}
      <fieldset className="rounded-md border border-ink-600 p-4">
        <legend className="px-1 text-sm font-semibold text-white">Scoring</legend>
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Mode">
            <select
              className={inputCls}
              value={q.scoring.mode}
              onChange={(e) => {
                const mode = e.target.value;
                const base =
                  mode === "ranked"
                    ? { mode, points: q.type === "super_fast" ? [4000, 3000, 2000] : [4000, 3200, 2400, 1600] }
                    : mode === "flat"
                      ? { mode, max: mcq ? 1000 : 4000 }
                      : mode === "speed_weighted"
                        ? { mode, max: 4000, speed_floor: 0.1, correctness_floor: 0.6, min_pass: 0.5 }
                        : defaultScoring(q.type);
                onChange({ scoring: base as FullQuestion["scoring"] });
              }}
            >
              {MODES[q.type].map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          {q.scoring.mode !== "ranked" && (
            <Field label="Max points">
              <input type="number" min={0} max={100000} className={inputCls} value={Number(q.scoring.max ?? (mcq ? 1000 : 4000))} onChange={(e) => setScoring({ max: Math.round(num(e.target.value, 4000)) })} />
            </Field>
          )}
          {q.scoring.mode === "speed_weighted" && (
            <>
              <Field label="Speed floor" hint="share at the buzzer">
                <input type="number" min={0} max={1} step={0.05} className={inputCls} value={Number(q.scoring.speed_floor)} onChange={(e) => setScoring({ speed_floor: num(e.target.value, 0.1) })} />
              </Field>
              <Field label="Correctness floor" hint="share at the minimum pass rate">
                <input type="number" min={0} max={1} step={0.05} className={inputCls} value={Number(q.scoring.correctness_floor)} onChange={(e) => setScoring({ correctness_floor: num(e.target.value, 0.6) })} />
              </Field>
              <Field label="Minimum pass rate">
                <input type="number" min={0} max={1} step={0.05} className={inputCls} value={Number(q.scoring.min_pass)} onChange={(e) => setScoring({ min_pass: num(e.target.value, 0.5) })} />
              </Field>
            </>
          )}
          {q.scoring.mode === "closest" && (
            <Field label="Minimum share" hint="every passing team gets at least this">
              <input type="number" min={0} max={1} step={0.05} className={inputCls} value={Number(q.scoring.min_share)} onChange={(e) => setScoring({ min_share: num(e.target.value, 0.5) })} />
            </Field>
          )}
          {q.scoring.mode === "ranked" && (
            <Field label={q.type === "super_fast" ? "Points for 1st, 2nd, 3rd…" : "Points by position"} hint="comma-separated; one per scoring place">
              <input
                className={inputCls}
                defaultValue={((q.scoring.points as number[]) ?? []).join(", ")}
                onBlur={(e) =>
                  setScoring({
                    points: e.target.value
                      .split(",")
                      .map((x) => parseInt(x.trim(), 10))
                      .filter((n) => Number.isFinite(n) && n >= 0),
                  })
                }
              />
            </Field>
          )}
        </div>
      </fieldset>
    </div>
  );
}

function McqAnswers({ q, onChange }: { q: FullQuestion; onChange: (patch: Partial<FullQuestion>) => void }) {
  const options = q.config.options ?? [];
  const correct = new Set(q.config.correct ?? []);
  const set = (next: { text: string }[], c: Set<number>) => onChange({ config: { ...q.config, options: next, correct: [...c].sort((a, b) => a - b) } });
  const colors = ["#EF4E6B", "#2E86DE", "#F0A03C", "#21A68D"];
  return (
    <div>
      <span className="mb-1 block text-sm font-semibold text-white">
        Answers <span className="font-normal text-ink-400">· 2 to 4; tick every correct one</span>
      </span>
      <div className="grid gap-2 md:grid-cols-2">
        {options.map((o, i) => (
          <div key={i} className="flex items-center gap-2 rounded-md p-2" style={{ background: `${colors[i]}33`, borderLeft: `6px solid ${colors[i]}` }}>
            <input
              value={o.text}
              maxLength={120}
              placeholder={`Answer ${i + 1}`}
              aria-label={`Answer ${i + 1}`}
              onChange={(e) => set(options.map((x, j) => (j === i ? { text: e.target.value } : x)), correct)}
              className="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none"
            />
            <label className="flex items-center gap-1 text-xs text-ink-200">
              <input
                type="checkbox"
                checked={correct.has(i)}
                aria-label={`Answer ${i + 1} is correct`}
                onChange={(e) => {
                  const c = new Set(correct);
                  if (e.target.checked) c.add(i);
                  else c.delete(i);
                  set(options, c);
                }}
              />
              correct
            </label>
            {options.length > 2 && (
              <button
                onClick={() => {
                  // drop answer i and shift the correct indexes above it
                  const c = new Set([...correct].filter((x) => x !== i).map((x) => (x > i ? x - 1 : x)));
                  set(
                    options.filter((_, j) => j !== i),
                    c,
                  );
                }}
                className="rounded px-1.5 text-ink-400 hover:text-fail"
                aria-label={`Remove answer ${i + 1}`}
              >
                ✕
              </button>
            )}
          </div>
        ))}
      </div>
      {options.length < 4 && (
        <button onClick={() => set([...options, { text: "" }], correct)} className="mt-2 rounded bg-ink-600 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:bg-ink-500">
          + Add answer
        </button>
      )}
    </div>
  );
}
