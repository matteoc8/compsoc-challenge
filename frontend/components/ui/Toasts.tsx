"use client";
import { AnimatePresence, motion } from "framer-motion";
import { useGame } from "@/lib/store";

export function Toasts() {
  const toasts = useGame((s) => s.toasts);
  const dismiss = useGame((s) => s.dismiss);
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-50 flex flex-col gap-2" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.button
            key={t.id}
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 40 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            onClick={() => dismiss(t.id)}
            className={`pointer-events-auto rounded-lg px-4 py-3 text-left font-stage text-base font-extrabold text-white shadow-xl ${
              t.tone === "good" ? "bg-pass" : t.tone === "bad" ? "bg-fail" : "bg-ink-600"
            }`}
          >
            {t.text}
          </motion.button>
        ))}
      </AnimatePresence>
    </div>
  );
}
