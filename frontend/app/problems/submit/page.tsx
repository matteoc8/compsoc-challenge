"use client";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import type { IOCase } from "@/lib/types";

const inputCls = "w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-white focus:border-round-blue focus:outline-none";

const EMPTY = { author_name: "", email: "", title: "", intended_use: "either", description_md: "", solution: "", notes: "", website: "" };

export default function SubmitProblemPage() {
  const [form, setForm] = useState(EMPTY);
  const [examples, setExamples] = useState<IOCase[]>([{ stdin: "", expected: "" }]);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/problems/submit", { body: { ...form, examples: examples.filter((x) => x.stdin.trim() || x.expected.trim()) } });
      setSent(true);
      setForm(EMPTY);
      setExamples([{ stdin: "", expected: "" }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send it");
    } finally {
      setBusy(false);
    }
  };

  if (sent)
    return (
      <div className="mx-auto max-w-xl rounded-lg bg-ink-800 p-6 text-center ring-1 ring-ink-600" role="status">
        <h1 className="font-stage text-3xl font-black text-white">Thanks!</h1>
        <p className="mt-2 text-ink-300">Your problem is in the queue. We review every one; good ones get featured or used in the Challenge.</p>
        <div className="mt-5 flex justify-center gap-3">
          <Button variant="secondary" onClick={() => setSent(false)}>
            Submit another
          </Button>
          <Link href="/problems" className="rounded-md bg-round-blue px-4 py-2 text-sm font-semibold text-white hover:brightness-110">
            Featured problems
          </Link>
        </div>
      </div>
    );

  return (
    <form onSubmit={submit} className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="font-stage text-4xl font-black text-white">Submit a problem</h1>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm font-semibold text-white">
          Your name
          <input className={`${inputCls} mt-1`} value={form.author_name} onChange={set("author_name")} maxLength={60} required />
        </label>
        <label className="block text-sm font-semibold text-white">
          Your email
          <input className={`${inputCls} mt-1`} type="email" value={form.email} onChange={set("email")} maxLength={200} autoComplete="email" required />
        </label>
        <label className="block text-sm font-semibold text-white">
          Problem title
          <input className={`${inputCls} mt-1`} value={form.title} onChange={set("title")} minLength={3} maxLength={120} required />
        </label>
        <label className="block text-sm font-semibold text-white">
          Preferred problem use
          <select className={`${inputCls} mt-1`} value={form.intended_use} onChange={set("intended_use")}>
            <option value="challenge">CompSoc Challenge</option>
            <option value="weekly">Weekly problem</option>
            <option value="either">Either</option>
          </select>
        </label>
      </div>
      {/* bot trap: hidden from people, filled in by spam scripts */}
      <input type="text" name="website" value={form.website} onChange={set("website")} tabIndex={-1} autoComplete="off" aria-hidden className="hidden" />
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-sm font-semibold text-white">
            Description <span className="font-normal text-ink-400">(Markdown works)</span>
          </span>
          <button type="button" onClick={() => setPreview(!preview)} className="text-xs text-round-blue hover:underline">
            {preview ? "Edit" : "Preview"}
          </button>
        </div>
        {preview ? (
          <div className="min-h-[180px] rounded-md border border-ink-600 bg-ink-800 p-3 text-sm text-ink-200">
            <Markdown>{form.description_md || "*Nothing yet*"}</Markdown>
          </div>
        ) : (
          <textarea className={`${inputCls} min-h-[180px]`} value={form.description_md} onChange={set("description_md")} minLength={10} maxLength={10000} required aria-label="Description" />
        )}
      </div>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-semibold text-white">
          Examples <span className="font-normal text-ink-400">(optional, up to 5)</span>
        </legend>
        {examples.map((x, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <textarea
              aria-label={`Example ${i + 1} input`}
              placeholder="Input"
              className={`${inputCls} font-mono`}
              rows={2}
              value={x.stdin}
              onChange={(e) => setExamples(examples.map((y, j) => (j === i ? { ...y, stdin: e.target.value } : y)))}
            />
            <textarea
              aria-label={`Example ${i + 1} output`}
              placeholder="Expected output"
              className={`${inputCls} font-mono`}
              rows={2}
              value={x.expected}
              onChange={(e) => setExamples(examples.map((y, j) => (j === i ? { ...y, expected: e.target.value } : y)))}
            />
            <button type="button" onClick={() => setExamples(examples.filter((_, j) => j !== i))} className="self-start rounded px-2 py-1 text-ink-400 hover:text-fail" aria-label={`Remove example ${i + 1}`}>
              ✕
            </button>
          </div>
        ))}
        {examples.length < 5 && (
          <button type="button" onClick={() => setExamples([...examples, { stdin: "", expected: "" }])} className="rounded bg-ink-600 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:bg-ink-500">
            + Add example
          </button>
        )}
      </fieldset>
      <label className="block text-sm font-semibold text-white">
        Your solution <span className="font-normal text-ink-400">(optional)</span>
        <textarea className={`${inputCls} mt-1 min-h-[140px] font-mono`} value={form.solution} onChange={set("solution")} maxLength={10000} spellCheck={false} />
      </label>
      <label className="block text-sm font-semibold text-white">
        Anything else? <span className="font-normal text-ink-400">(optional)</span>
        <textarea className={`${inputCls} mt-1`} rows={2} value={form.notes} onChange={set("notes")} maxLength={2000} />
      </label>
      {error && (
        <p className="rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </p>
      )}
      <Button size="lg" disabled={busy}>
        {busy ? "Sending…" : "Submit problem"}
      </Button>
    </form>
  );
}
