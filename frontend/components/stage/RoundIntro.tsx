"use client";
import { motion, useReducedMotion } from "framer-motion";
import { TYPE_ACCENT } from "@/lib/format";
import type { Snapshot } from "@/lib/types";

export function RoundIntro({ intro, compact = false }: { intro: NonNullable<Snapshot["intro"]>; compact?: boolean }) {
  const reduce = useReducedMotion();
  const accent = TYPE_ACCENT[intro.type];
  return (
    <div className="flex h-full items-center justify-center p-6" style={{ background: `radial-gradient(circle at 50% 40%, ${accent}cc, #160F52 72%)` }}>
      <motion.div
        initial={reduce ? { opacity: 0 } : { scale: 0.5, opacity: 0, rotate: -4 }}
        animate={{ scale: 1, opacity: 1, rotate: 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 25 }}
        className="text-center"
      >
        <div className={`font-stage font-bold uppercase tracking-[0.3em] text-white/80 ${compact ? "text-base" : "text-2xl"}`}>
          {intro.position} of {intro.count} · {intro.type_label}
        </div>
        <h1 className={`mt-4 font-stage font-black text-white drop-shadow-lg ${compact ? "text-4xl" : "text-8xl"}`}>{intro.round_name}</h1>
        {intro.question_text && (
          <p className={`mx-auto mt-6 max-w-5xl font-stage font-black text-white ${compact ? "text-2xl" : "text-6xl"}`}>{intro.question_text}</p>
        )}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: reduce ? 0 : 0.6, duration: 0.3 }}
          className={`mx-auto mt-6 max-w-5xl font-stage font-extrabold text-white ${compact ? "text-xl" : "text-4xl"}`}
        >
          {intro.rule_line}
        </motion.p>
      </motion.div>
    </div>
  );
}
