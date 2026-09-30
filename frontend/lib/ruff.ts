"use client";
// Main-thread side of the Ruff worker: a CodeMirror linter and a formatter.
import type { Diagnostic as CMDiagnostic } from "@codemirror/lint";
import { linter } from "@codemirror/lint";
import type { Extension } from "@codemirror/state";
import type { EditorView } from "@codemirror/view";

interface RuffDiagnostic {
  code: string | null;
  message: string;
  start_location: { row: number; column: number };
  end_location: { row: number; column: number };
}

let worker: Worker | null = null;
let failed = false;
let seq = 0;
const pending = new Map<number, (v: { ok: boolean; result?: unknown; error?: string }) => void>();
const listeners = new Set<(ok: boolean) => void>();

function getWorker(): Worker | null {
  if (failed || typeof window === "undefined") return null;
  if (worker) return worker;
  try {
    worker = new Worker(new URL("./ruff.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (e) => {
      const { id, ...rest } = e.data;
      if (id === -1) {
        markFailed();
        return;
      }
      pending.get(id)?.(rest);
      pending.delete(id);
    };
    worker.onerror = () => markFailed();
  } catch {
    markFailed();
  }
  return worker;
}

function markFailed() {
  failed = true;
  pending.forEach((resolve) => resolve({ ok: false, error: "Ruff unavailable" }));
  pending.clear();
  listeners.forEach((l) => l(false));
}

export function onRuffStatus(fn: (ok: boolean) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function call(kind: "lint" | "format", code: string, timeoutMs = 8000): Promise<{ ok: boolean; result?: unknown; error?: string }> {
  const w = getWorker();
  if (!w) return Promise.resolve({ ok: false, error: "Ruff unavailable" });
  const id = ++seq;
  return new Promise((resolve) => {
    const t = setTimeout(() => {
      pending.delete(id);
      resolve({ ok: false, error: "timeout" });
    }, timeoutMs);
    pending.set(id, (v) => {
      clearTimeout(t);
      resolve(v);
    });
    w.postMessage({ id, kind, code });
  });
}

const ERROR_CODES = /^(invalid-syntax|E9|F82|F63|F7|F50|F52|E1(0|1)[12])/;

function toCM(view: EditorView, d: RuffDiagnostic): CMDiagnostic {
  const doc = view.state.doc;
  const pos = (row: number, col: number) => {
    const line = doc.line(Math.min(Math.max(row, 1), doc.lines));
    return Math.min(line.from + Math.max(col - 1, 0), line.to);
  };
  const from = pos(d.start_location.row, d.start_location.column);
  let to = pos(d.end_location.row, d.end_location.column);
  if (to <= from) to = Math.min(from + 1, doc.length);
  const code = d.code || "invalid-syntax";
  return {
    from,
    to,
    severity: code === "invalid-syntax" || ERROR_CODES.test(code) ? "error" : "warning",
    message: d.message,
    source: code === "invalid-syntax" ? "syntax" : code,
  };
}

export function ruffLinter(): Extension {
  return linter(
    async (view) => {
      const res = await call("lint", view.state.doc.toString());
      if (!res.ok || !Array.isArray(res.result)) return [];
      return (res.result as RuffDiagnostic[]).map((d) => toCM(view, d));
    },
    { delay: 300 },
  );
}

export async function formatPython(code: string): Promise<{ ok: boolean; code?: string; error?: string }> {
  const res = await call("format", code);
  return res.ok ? { ok: true, code: String(res.result) } : { ok: false, error: res.error };
}

/** Warm the worker up early (the WASM is ~10 MB). */
export function preloadRuff() {
  getWorker();
}
