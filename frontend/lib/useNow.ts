"use client";
import { useEffect, useState } from "react";

/** Re-render every `ms` milliseconds (for countdowns). */
export function useNow(ms = 200): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
