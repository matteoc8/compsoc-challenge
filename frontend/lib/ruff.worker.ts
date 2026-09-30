/// <reference lib="webworker" />
// Ruff (compiled to WebAssembly) off the main thread: lint as you type, and format.
import init, { PositionEncoding, Workspace } from "@astral-sh/ruff-wasm-web";

declare const self: DedicatedWorkerGlobalScope;

const SETTINGS = {
  "target-version": "py38", // Judge0 CE runs Python 3.8
  "line-length": 100,
  lint: {
    // errors-only: syntax, pyflakes (undefined names, unused variables…), indentation, tabs
    select: ["E9", "F", "E1", "W191"],
    preview: true, // the E1 indentation rules are preview-only in Ruff
  },
  format: { "indent-style": "space", "quote-style": "preserve" },
};

let workspace: Workspace | null = null;
const ready = init()
  .then(() => {
    workspace = new Workspace(SETTINGS, PositionEncoding.Utf16);
  })
  .catch((e) => {
    self.postMessage({ id: -1, ok: false, error: String(e) });
  });

self.onmessage = async (e: MessageEvent<{ id: number; kind: "lint" | "format"; code: string }>) => {
  const { id, kind, code } = e.data;
  await ready;
  if (!workspace) {
    self.postMessage({ id, ok: false, error: "Ruff failed to load" });
    return;
  }
  try {
    const result = kind === "lint" ? workspace.check(code) : workspace.format(code);
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    // format() throws on syntax errors
    self.postMessage({ id, ok: false, error: String(err) });
  }
};
