"use client";
// Hints the host has sent this team for the current question: the latest one in a strip
// under the header, the rest a click away.

import { useState } from "react";
import { EMPTY_LIST, useGame } from "@/lib/store";
import type { Hint } from "@/lib/types";

export function HintsStrip() {
  const hints = useGame((s) => (s.snapshot?.my_hints ?? EMPTY_LIST) as Hint[]);
  const [open, setOpen] = useState(false);
  if (!hints.length) return null;
  const latest = hints[hints.length - 1];
  return (
    <div className="border-b border-round-yellow/40 bg-round-yellow/15 px-4 py-1.5 text-sm text-white" role="status">
      {open ? (
        <ul className="space-y-1">
          {hints.map((h) => (
            <li key={h.index}>
              <b className="text-round-yellow">Hint {h.number}:</b> {h.text}
            </li>
          ))}
        </ul>
      ) : (
        <span>
          <b className="text-round-yellow">Hint {latest.number}:</b> {latest.text}
        </span>
      )}
      {hints.length > 1 && (
        <button onClick={() => setOpen(!open)} className="ml-3 text-xs font-semibold text-round-yellow underline">
          {open ? "Show latest only" : `All ${hints.length} hints`}
        </button>
      )}
    </div>
  );
}
