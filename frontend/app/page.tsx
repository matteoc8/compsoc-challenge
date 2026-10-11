import Link from "next/link";
import { LatestProblems, SchoolBoardCard, WeeklyCard } from "@/components/site/HomeDashboard";
import { SiteShell } from "@/components/site/SiteShell";
import { BRAND } from "@/lib/brand";

const card = "group flex flex-col rounded-xl bg-ink-800 p-6 ring-1 ring-ink-600 hover:bg-ink-700";

export default function Home() {
  return (
    <SiteShell>
      <section className="stage-bg relative flex min-h-[260px] items-center overflow-hidden rounded-2xl px-6 shadow-xl sm:px-12">
        <div aria-hidden className="pointer-events-none absolute -right-6 top-1/2 hidden -translate-y-1/2 select-none font-mono text-[11rem] font-black leading-none text-white/[0.06] md:block">
          {"{ }"}
        </div>
        <h1 className="font-stage text-6xl font-black text-white sm:text-8xl">{BRAND.site}</h1>
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <WeeklyCard />
        <SchoolBoardCard />
      </div>

      <div className="mt-10">
        <LatestProblems />
      </div>

      <div className="mt-10 grid gap-6 md:grid-cols-2">
        <Link href="/challenge" className={card}>
          <h2 className="font-stage text-2xl font-black text-white">{BRAND.event}</h2>
          <span className="mt-3 text-sm font-semibold text-accent group-hover:underline">Join a game →</span>
        </Link>
        <Link href="/problems/submit" className={card}>
          <h2 className="font-stage text-2xl font-black text-white">Submit a problem</h2>
          <span className="mt-3 text-sm font-semibold text-accent group-hover:underline">Suggest one →</span>
        </Link>
      </div>
    </SiteShell>
  );
}
