import type { Metadata } from "next";
import { SiteShell } from "@/components/site/SiteShell";

export const metadata: Metadata = { title: "Problem of the week" };

export default function WeeklyLayout({ children }: { children: React.ReactNode }) {
  return <SiteShell>{children}</SiteShell>;
}
