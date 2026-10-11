/** A leaderboard position: gold, silver and bronze discs for the top three, a plain number after. */
const PODIUM = ["bg-accent text-black", "bg-ink-200 text-black", "bg-[#C98552] text-black"];

export function Rank({ rank }: { rank: number }) {
  return (
    <span className={`inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 text-xs font-bold tabular-nums ${PODIUM[rank - 1] ?? "text-ink-300"}`}>
      {rank}
    </span>
  );
}
