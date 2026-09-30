"use client";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost" | "success" | "stage";

const STYLES: Record<Variant, string> = {
  primary: "bg-round-blue text-white hover:brightness-110",
  secondary: "bg-ink-600 text-ink-200 hover:bg-ink-500",
  danger: "bg-round-red text-white hover:brightness-110",
  ghost: "bg-transparent text-ink-300 hover:bg-ink-700",
  success: "bg-round-green text-white hover:brightness-110",
  stage: "bg-accent text-black font-stage font-extrabold hover:bg-accent-light",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg" }) {
  const sz = size === "sm" ? "px-2.5 py-1 text-xs" : size === "lg" ? "px-6 py-3 text-lg" : "px-4 py-2 text-sm";
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-md font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 ${sz} ${STYLES[variant]} ${className}`}
    />
  );
}
