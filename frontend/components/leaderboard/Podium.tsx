"use client";
import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";
import { fmtPoints } from "@/lib/format";
import type { BoardRow } from "@/lib/types";

const HEIGHT = { 1: "h-80", 2: "h-60", 3: "h-44" } as const;
const COLOR = { 1: "#F6B73C", 2: "#A9B4D0", 3: "#D0864B" } as const;

// 3rd, then 2nd, then (after a pause) 1st rise in turn, then confetti.
export function Podium({ rows, compact = false }: { rows: BoardRow[]; compact?: boolean }) {
  const reduce = useReducedMotion();
  const [step, setStep] = useState(reduce ? 3 : 0);
  const byPlace = [1, 2, 3].map((p) => rows.filter((r) => r.rank === p));

  useEffect(() => {
    if (reduce) return;
    const t = [setTimeout(() => setStep(1), 800), setTimeout(() => setStep(2), 2600), setTimeout(() => setStep(3), 5600)];
    return () => t.forEach(clearTimeout);
  }, [reduce]);

  useEffect(() => {
    if (step !== 3 || compact) return;
    let stop = false;
    import("canvas-confetti").then(({ default: confetti }) => {
      if (stop) return;
      const end = Date.now() + 3000;
      const frame = () => {
        confetti({ particleCount: 6, angle: 60, spread: 70, origin: { x: 0 }, disableForReducedMotion: true });
        confetti({ particleCount: 6, angle: 120, spread: 70, origin: { x: 1 }, disableForReducedMotion: true });
        if (Date.now() < end && !stop) requestAnimationFrame(frame);
      };
      frame();
    });
    return () => {
      stop = true;
    };
  }, [step, compact]);

  const visible = (place: 1 | 2 | 3) => (place === 3 ? step >= 1 : place === 2 ? step >= 2 : step >= 3);
  const col = (place: 1 | 2 | 3) => {
    const teams = byPlace[place - 1];
    return (
      <div key={place} className="flex w-1/3 max-w-xs flex-col items-center justify-end">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={visible(place) ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
          transition={{ duration: 0.3 }}
          className="mb-3 text-center font-stage text-white"
        >
          {teams.length ? (
            <>
              <div className={`font-black leading-tight ${compact ? "text-xl" : "text-4xl"}`}>{teams.map((t) => t.name).join(" & ")}</div>
              <div className={`font-bold text-white/80 ${compact ? "text-base" : "text-2xl"}`}>{fmtPoints(teams[0].points)}</div>
            </>
          ) : (
            <div className="text-2xl font-bold text-white/50">–</div>
          )}
        </motion.div>
        <motion.div
          initial={{ scaleY: 0 }}
          animate={{ scaleY: visible(place) ? 1 : 0 }}
          style={{ originY: 1, background: COLOR[place] }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          className={`flex w-full items-start justify-center rounded-t-xl pt-4 font-stage font-black text-white shadow-2xl ${compact ? "h-24 text-4xl" : `${HEIGHT[place]} text-8xl`}`}
        >
          {place}
        </motion.div>
      </div>
    );
  };
  return (
    <div className="flex h-full flex-col items-center justify-end px-6 pb-0 pt-6">
      <h1 className={`mb-auto font-stage font-black text-white ${compact ? "text-3xl" : "text-6xl"}`}>Podium</h1>
      <div className="flex w-full max-w-5xl items-end justify-center gap-4">{[2, 1, 3].map((p) => col(p as 1 | 2 | 3))}</div>
    </div>
  );
}
