"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { BRAND } from "@/lib/brand";
import { logout, type AdminMe } from "@/lib/admin";

const LINKS = [
  { href: "/admin", label: "Challenge" },
  { href: "/admin/weekly", label: "Problem of the week" },
  { href: "/admin/people", label: "People" },
  { href: "/admin/problems", label: "Problem queue" },
  { href: "/admin/featured", label: "Featured problems" },
];

/** Header for the admin pages; `pending` lets the queue page keep the badge in step. */
export function AdminNav({ me, pending }: { me: AdminMe; pending?: number }) {
  const path = usePathname();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    if (pending !== undefined) return;
    api<{ counts: { pending: number } }>("/problem-submissions?status=pending")
      .then((r) => setCount(r.counts.pending))
      .catch(() => undefined);
  }, [pending]);
  const waiting = pending ?? count;
  return (
    <header className="mb-8 flex flex-wrap items-center gap-x-6 gap-y-3">
      <Link href="/" className="font-stage text-3xl font-black text-white">
        {BRAND.site}
      </Link>
      <nav className="flex flex-wrap gap-1 text-sm" aria-label="Admin">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            aria-current={path === l.href ? "page" : undefined}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 font-semibold ${path === l.href ? "bg-ink-600 text-white" : "text-ink-300 hover:bg-ink-700 hover:text-white"}`}
          >
            {l.label}
            {l.href === "/admin/problems" && !!waiting && <span className="rounded-full bg-accent px-1.5 text-xs font-bold text-black">{waiting}</span>}
          </Link>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-3 text-sm text-ink-400">
        {me.username}
        <Button variant="ghost" size="sm" onClick={logout}>
          Log out
        </Button>
      </div>
    </header>
  );
}
