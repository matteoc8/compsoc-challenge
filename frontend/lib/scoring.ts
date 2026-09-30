// Client-side estimate for the Super Fast "points if you submit now" meter. The server's
// scoring (backend/app/engine/scoring.py) is authoritative.
export function superFastEstimate(
  scoring: Record<string, unknown> | undefined,
  elapsedMs: number,
  limitMs: number,
  passFraction = 1,
): number {
  const max = Number(scoring?.max ?? 4000);
  const speedFloor = Number(scoring?.speed_floor ?? 0.1);
  const cf = Number(scoring?.correctness_floor ?? 0.6);
  const minPass = Number(scoring?.min_pass ?? 0.5);
  if (passFraction < minPass || passFraction === 0) return 0;
  const t = limitMs > 0 ? Math.min(Math.max(elapsedMs, 0), limitMs) / limitMs : 1;
  return Math.floor(max * (1 - (1 - speedFloor) * t) * (cf + (1 - cf) * passFraction) + 0.5);
}
