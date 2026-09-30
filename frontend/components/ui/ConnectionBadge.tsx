"use client";
import { useGame } from "@/lib/store";

export function ConnectionBadge({ className = "" }: { className?: string }) {
  const status = useGame((s) => s.status);
  if (status === "open") return null;
  const text = status === "connecting" ? "Connecting…" : status === "reconnecting" ? "Reconnecting…" : null;
  if (!text) return null;
  return (
    <div className={`fixed bottom-3 left-1/2 z-50 -translate-x-1/2 rounded-full bg-round-yellow px-4 py-1.5 text-sm font-bold text-black shadow-lg ${className}`} role="status">
      {text}
    </div>
  );
}
