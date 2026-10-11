import type { Metadata } from "next";
import Link from "next/link";
import { BRAND } from "@/lib/brand";

export const metadata: Metadata = { title: "Challenge" };

// Full-screen, like the game screens it leads to: join as a team, or run the game.
export default function ChallengePage() {
  return (
    <main className="stage-bg relative flex min-h-full flex-col items-center justify-center p-6 text-center">
      <Link href="/" className="absolute left-5 top-4 font-stage text-lg font-black text-white/70 hover:text-white">
        ← {BRAND.site}
      </Link>
      <h1 className="font-stage text-6xl font-black text-white sm:text-8xl">{BRAND.event}</h1>
      <div className="mt-12 flex w-full max-w-xl flex-col gap-4 sm:flex-row">
        <Link href="/join" className="flex-1 rounded-xl bg-accent px-8 py-6 font-stage text-3xl font-black text-black shadow-2xl hover:bg-accent-light">
          Join a game
        </Link>
        <Link href="/admin" className="flex-1 rounded-xl border-2 border-white/25 px-8 py-6 font-stage text-3xl font-black text-white hover:bg-white/10">
          Host portal
        </Link>
      </div>
    </main>
  );
}
