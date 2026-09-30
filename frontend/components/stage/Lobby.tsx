"use client";
import { AnimatePresence, motion } from "framer-motion";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { BRAND } from "@/lib/brand";
import { useGame } from "@/lib/store";

export function Lobby() {
  const snap = useGame((s) => s.snapshot);
  const [qr, setQr] = useState<string | null>(null);
  const code = snap?.game.join_code ?? "";
  const joinUrl = typeof window !== "undefined" ? `${window.location.origin}/join` : "/join";

  useEffect(() => {
    if (!code) return;
    QRCode.toDataURL(`${window.location.origin}/join?code=${code}`, { margin: 1, width: 320, color: { dark: "#160F52", light: "#ffffff" } })
      .then(setQr)
      .catch(() => setQr(null));
  }, [code]);

  const teams = snap?.teams ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-10 border-b-4 border-accent bg-stage-deep px-10 py-6 shadow-2xl">
        <div className="font-stage text-4xl font-black text-white">{BRAND.event}</div>
        <div className="ml-auto text-right">
          <div className="font-stage text-2xl font-bold text-white/70">Join at</div>
          <div className="font-stage text-4xl font-black text-white">{joinUrl.replace(/^https?:\/\//, "")}</div>
        </div>
        <div className="text-center">
          <div className="font-stage text-2xl font-bold text-white/70">Game code</div>
          <div className="font-stage text-7xl font-black tracking-[0.15em] text-accent" data-testid="join-code">
            {code}
          </div>
        </div>
        {qr && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={qr} alt={`QR code for ${joinUrl}?code=${code}`} className="h-36 w-36 rounded-lg" />
        )}
      </div>
      <div className="flex-1 overflow-hidden p-10">
        <div className="mb-6 flex items-center gap-4">
          <span className="rounded-lg bg-accent px-4 py-2 font-stage text-3xl font-black text-black">{teams.length}</span>
          <span className="font-stage text-2xl font-extrabold text-white">{teams.length === 1 ? "team" : "teams"}</span>
          {!teams.length && <span className="font-stage text-xl font-bold text-white/70">Waiting for teams to join…</span>}
        </div>
        <div className="flex flex-wrap gap-4">
          <AnimatePresence>
            {teams.map((t) => (
              <motion.div
                key={t.team_id}
                layout
                initial={{ scale: 0.4, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.4, opacity: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 25 }}
                className={`rounded-lg px-6 py-3 font-stage text-2xl font-extrabold shadow-lg ${t.online ? "bg-white text-stage-deep" : "bg-white/40 text-stage-deep/70"}`}
              >
                {t.name}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
