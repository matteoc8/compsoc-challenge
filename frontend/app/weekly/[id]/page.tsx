"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { WeeklyProblem } from "@/components/site/WeeklyProblem";

export default function WeeklyById() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <Link href="/weekly" className="mb-4 inline-block text-sm text-ink-400 hover:text-white">
        ← Problem of the week
      </Link>
      <WeeklyProblem id={id} />
    </>
  );
}
