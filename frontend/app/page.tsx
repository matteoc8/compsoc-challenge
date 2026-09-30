import Link from "next/link";
import { BRAND } from "@/lib/brand";

export default function Home() {
  return (
    <main className="stage-bg flex min-h-full flex-col items-center justify-center gap-10 p-6 text-center">
      <h1 className="font-stage text-5xl font-black text-white sm:text-7xl">{BRAND.event}</h1>
      <div className="flex flex-wrap justify-center gap-4">
        <Link href="/join" className="rounded-lg bg-accent px-8 py-4 font-stage text-2xl font-black text-black shadow-xl hover:bg-accent-light">
          Join a game
        </Link>
        <Link href="/teacher" className="rounded-lg border-2 border-white/25 px-8 py-4 font-stage text-2xl font-black text-white hover:bg-white/10">
          Teacher
        </Link>
      </div>
    </main>
  );
}
