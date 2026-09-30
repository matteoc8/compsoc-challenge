"use client";
// Four answer tiles, each with its own colour AND shape so they're distinguishable
// without relying on colour alone.

import { motion } from "framer-motion";

export const TILE = [
  { color: "#EF4E6B", shape: "star", name: "Coral star" },
  { color: "#2E86DE", shape: "hexagon", name: "Blue hexagon" },
  { color: "#F0A03C", shape: "circle", name: "Amber circle" },
  { color: "#21A68D", shape: "square", name: "Teal square" },
] as const;

export function Shape({ i, size = 28 }: { i: number; size?: number }) {
  const s = TILE[i % 4].shape;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className="shrink-0">
      {s === "star" && <polygon points="12,1.5 14.9,8.6 22.5,9.2 16.7,14.2 18.5,21.6 12,17.6 5.5,21.6 7.3,14.2 1.5,9.2 9.1,8.6" fill="#fff" />}
      {s === "hexagon" && <polygon points="12,1.5 21.5,7 21.5,17 12,22.5 2.5,17 2.5,7" fill="#fff" />}
      {s === "circle" && <circle cx="12" cy="12" r="10.5" fill="#fff" />}
      {s === "square" && <rect x="2.5" y="2.5" width="19" height="19" fill="#fff" />}
    </svg>
  );
}

export function AnswerTiles({
  options,
  onPick,
  picked,
  disabled = false,
  reveal,
  size = "md",
}: {
  options: { index: number; text: string }[];
  onPick?: (i: number) => void;
  picked?: number | null;
  disabled?: boolean;
  reveal?: { correct: boolean[]; counts?: number[] };
  size?: "md" | "lg";
}) {
  const big = size === "lg";
  return (
    <div className={`grid h-full grid-cols-2 ${big ? "gap-4" : "gap-3"}`}>
      {options.map((o) => {
        const t = TILE[o.index % 4];
        const dim = (picked != null && picked !== o.index) || (reveal && !reveal.correct[o.index]);
        const Tag = onPick ? motion.button : motion.div;
        return (
          <Tag
            key={o.index}
            {...(onPick ? { onClick: () => onPick(o.index), disabled, "aria-label": `${t.name}: ${o.text}` } : {})}
            whileTap={onPick && !disabled ? { scale: 0.96 } : undefined}
            className={`relative flex min-h-[72px] items-center gap-4 rounded-lg text-left font-stage font-extrabold text-white shadow-lg transition-opacity ${
              big ? "px-7 py-6 text-4xl" : "px-5 py-4 text-xl"
            } ${dim ? "opacity-35" : ""} ${onPick && !disabled ? "hover:brightness-110" : ""}`}
            style={{ background: t.color }}
          >
            <Shape i={o.index} size={big ? 44 : 28} />
            <span className="min-w-0 flex-1 break-words leading-tight">{o.text}</span>
            {reveal?.correct[o.index] && (
              <span className={`${big ? "text-5xl" : "text-3xl"}`} aria-label="correct answer">
                ✓
              </span>
            )}
            {reveal?.counts && <span className={`tabular-nums ${big ? "text-4xl" : "text-2xl"}`}>{reveal.counts[o.index]}</span>}
          </Tag>
        );
      })}
    </div>
  );
}

/** Results: one bar per answer, the correct one(s) ticked. */
export function AnswerBars({ options, compact = false }: { options: { index: number; text: string; correct: boolean; count: number }[]; compact?: boolean }) {
  const max = Math.max(1, ...options.map((o) => o.count));
  return (
    <div className={`flex items-end justify-center ${compact ? "h-40 gap-3" : "h-72 gap-8"}`}>
      {options.map((o) => {
        const t = TILE[o.index % 4];
        return (
          <div key={o.index} className={`flex h-full flex-col items-center justify-end ${compact ? "w-16" : "w-32"}`}>
            <span className={`mb-1 font-stage font-black text-white ${compact ? "text-xl" : "text-4xl"}`}>
              {o.count} {o.correct && "✓"}
            </span>
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: `${(o.count / max) * 100}%` }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
              className={`flex w-full items-start justify-center rounded-t-md pt-2 ${o.correct ? "" : "opacity-40"}`}
              style={{ background: t.color, minHeight: compact ? 30 : 48 }}
            >
              <Shape i={o.index} size={compact ? 18 : 30} />
            </motion.div>
          </div>
        );
      })}
    </div>
  );
}
