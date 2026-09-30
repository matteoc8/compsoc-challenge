"use client";
// Expected vs actual, line by line, using the judge's comparison rule
// (trailing whitespace per line and trailing blank lines are ignored).

function norm(s: string): string[] {
  const lines = s.replace(/\r\n/g, "\n").split("\n").map((l) => l.replace(/\s+$/, ""));
  while (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

export function OutputDiff({ expected, actual }: { expected: string; actual: string }) {
  const e = norm(expected);
  const a = norm(actual);
  const n = Math.max(e.length, a.length, 1);
  const rows = Array.from({ length: n }, (_, i) => ({ e: e[i], a: a[i], ok: e[i] === a[i] }));
  return (
    <div className="grid grid-cols-2 gap-2 font-mono text-xs">
      <div>
        <div className="mb-1 text-[11px] uppercase text-ink-400">Expected</div>
        <pre className="overflow-x-auto rounded bg-ink-900 p-2">
          {rows.map((r, i) => (
            <div key={i} className={r.ok ? "text-ink-200" : "bg-pass/10 text-pass"}>
              {r.e === undefined ? <span className="opacity-40">∅</span> : r.e || " "}
            </div>
          ))}
        </pre>
      </div>
      <div>
        <div className="mb-1 text-[11px] uppercase text-ink-400">Your output</div>
        <pre className="overflow-x-auto rounded bg-ink-900 p-2">
          {rows.map((r, i) => (
            <div key={i} className={r.ok ? "text-ink-200" : "bg-fail/10 text-fail"}>
              {r.a === undefined ? <span className="opacity-40">∅</span> : r.a || " "}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
