import type { Metadata } from "next";
import { SiteShell } from "@/components/site/SiteShell";

export const metadata: Metadata = { title: "Problems" };

export default function ProblemsLayout({ children }: { children: React.ReactNode }) {
  return <SiteShell>{children}</SiteShell>;
}
