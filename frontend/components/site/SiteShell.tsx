"use client";
// The public site's frame: CompSoc header with its sections. The game screens (/join, /play,
// /presentation) and the admin pages keep their own full-screen layouts.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BRAND } from "@/lib/brand";
import { SECTIONS } from "@/lib/sections";

export function SiteShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  // the most specific section that matches, so /problems/submit doesn't also light up Problems
  const active = SECTIONS.filter((s) => path === s.href || path.startsWith(s.href + "/")).sort((a, b) => b.href.length - a.href.length)[0]?.href;
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-ink-600 bg-ink-800">
        <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3" aria-label="Site">
          <Link href="/" className="font-stage text-xl font-black text-white">
            {BRAND.site}
          </Link>
          <ul className="flex flex-wrap gap-1 text-sm">
            {SECTIONS.map((s) => (
              <li key={s.href}>
                <Link
                  href={s.href}
                  aria-current={active === s.href ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 font-semibold ${active === s.href ? "bg-ink-600 text-white" : "text-ink-300 hover:bg-ink-700 hover:text-white"}`}
                >
                  {s.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
