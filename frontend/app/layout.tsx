import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Montserrat } from "next/font/google";
import "./globals.css";

const stage = Montserrat({ subsets: ["latin"], weight: ["700", "800", "900"], variable: "--font-stage", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "CompSoc Challenge",
  description: "Live coding rounds for the CompSoc competition",
};

export const viewport: Viewport = { themeColor: "#3226A0" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB" className={`${stage.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
