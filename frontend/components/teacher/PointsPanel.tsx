"use client";
// Leaderboard with add/take-away points, moderation, and the adjustments log with Undo.

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { fmtPoints } from "@/lib/format";
import { EMPTY_LIST, useGame } from "@/lib/store";

export function PointsPanel({ gameId, onError }: { gameId: string; onError: (m: string | null) => void }) {
  const board = useGame((s) => s.snapshot?.leaderboard ?? EMPTY_LIST);
  const adjustments = useGame((s) => s.snapshot?.adjustments ?? EMPTY_LIST);
  const teams = useGame((s) => s.snapshot?.teams ?? EMPTY_LIST);
  const [note, setNote] = useState("");
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [rename, setRename] = useState<{ id: string; name: string } | null>(null);
  const [kick, setKick] = useState<{ id: string; name: string } | null>(null);
  const [rejoin, setRejoin] = useState<{ name: string; code: string } | null>(null);
  const [manage, setManage] = useState<{ id: string; name: string } | null>(null);
  const online = new Set(teams.filter((t) => t.online).map((t) => t.team_id));

  const call = async (path: string, body: unknown = {}) => {
    setBusy(true);
    onError(null);
    try {
      return await api(`/games/${gameId}/${path}`, { body });
    } catch (e) {
      onError(e instanceof ApiError ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const give = (teamId: string, points: number) => {
    if (!points) return;
    void call(`teams/${teamId}/points`, { points, note: note.trim() || null });
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-ink-800 ring-1 ring-ink-600">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 px-3 py-2">
          <h3 className="font-bold text-white">Teams and points</h3>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value.slice(0, 120))}
            placeholder="Reason (optional), e.g. cleanest code"
            className="ml-auto w-64 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-xs text-white"
            aria-label="Reason for points change"
          />
        </div>
        <div className="max-h-[420px] overflow-y-auto">
          {board.map((r) => (
            <div key={r.team_id} className="flex items-center gap-1 border-b border-ink-700 px-3 py-1.5 last:border-0">
              <span className="w-6 text-right font-mono text-xs text-ink-400">{r.rank}</span>
              <span className={`inline-block h-2 w-2 rounded-full ${online.has(r.team_id) ? "bg-pass" : "bg-ink-500"}`} />
              <span className="min-w-0 flex-1 truncate text-sm text-white">{r.name}</span>
              <span className="mr-1 w-16 shrink-0 text-right font-mono text-sm text-white">{fmtPoints(r.points)}</span>
              {[100, 500, -100, -500].map((d) => (
                <button
                  key={d}
                  disabled={busy}
                  onClick={() => give(r.team_id, d)}
                  className={`shrink-0 rounded px-1 py-0.5 font-mono text-[11px] font-bold ${d > 0 ? "bg-pass/20 text-pass hover:bg-pass/30" : "bg-fail/20 text-fail hover:bg-fail/30"}`}
                  aria-label={`${d > 0 ? "Add" : "Take away"} ${Math.abs(d)} points ${d > 0 ? "to" : "from"} ${r.name}`}
                >
                  {d > 0 ? `+${d}` : `−${-d}`}
                </button>
              ))}
              <input
                type="number"
                value={custom[r.team_id] ?? ""}
                onChange={(e) => setCustom({ ...custom, [r.team_id]: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    give(r.team_id, Math.round(Number(custom[r.team_id])));
                    setCustom({ ...custom, [r.team_id]: "" });
                  }
                }}
                placeholder="±"
                aria-label={`Custom points for ${r.name}`}
                className="w-14 shrink-0 rounded border border-ink-600 bg-ink-900 px-1 py-0.5 text-right font-mono text-xs text-white"
              />
              <button
                onClick={() => setManage({ id: r.team_id, name: r.name })}
                className="shrink-0 rounded px-1.5 text-ink-400 hover:bg-ink-700 hover:text-white"
                aria-label={`Manage ${r.name}`}
              >
                ⋯
              </button>
            </div>
          ))}
          {!board.length && <p className="p-3 text-sm text-ink-400">No teams yet.</p>}
        </div>
      </div>

      <div className="rounded-lg bg-ink-800 ring-1 ring-ink-600">
        <h3 className="border-b border-ink-600 px-3 py-2 font-bold text-white">Adjustments log</h3>
        <div className="max-h-56 overflow-y-auto">
          {adjustments.map((a) => (
            <div key={a.id} className={`flex items-center gap-2 border-b border-ink-700 px-3 py-1.5 text-sm last:border-0 ${a.undone ? "opacity-50" : ""}`}>
              <span className={`w-16 text-right font-mono ${a.points > 0 ? "text-pass" : "text-fail"}`}>
                {a.points > 0 ? "+" : ""}
                {a.points}
              </span>
              <span className="text-white">{a.team}</span>
              <span className="flex-1 truncate text-xs text-ink-400">{a.note}</span>
              {a.reason === "manual" && !a.undone && (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => call(`score-events/${a.id}/undo`)}>
                  Undo
                </Button>
              )}
              {a.undone && <span className="text-xs text-ink-400">undone</span>}
            </div>
          ))}
          {!adjustments.length && <p className="p-3 text-sm text-ink-400">No manual changes yet.</p>}
        </div>
      </div>

      <Modal open={!!manage} title={`Manage ${manage?.name}`} onClose={() => setManage(null)}>
        <div className="flex flex-col gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              setRename(manage);
              setManage(null);
            }}
          >
            Rename
          </Button>
          <Button
            variant="secondary"
            onClick={async () => {
              const m = manage!;
              setManage(null);
              const res = (await call(`teams/${m.id}/reissue`)) as { rejoin_code: string } | null;
              if (res) setRejoin({ name: m.name, code: res.rejoin_code });
            }}
          >
            Reissue: move to another computer
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setKick(manage);
              setManage(null);
            }}
          >
            Kick
          </Button>
        </div>
      </Modal>
      <Modal
        open={!!rename}
        title={`Rename ${rename?.name}`}
        onClose={() => setRename(null)}
        confirmLabel="Rename"
        onConfirm={async () => {
          const r = rename!;
          setRename(null);
          await call(`teams/${r.id}/rename`, { name: r.name });
        }}
      >
        <input value={rename?.name ?? ""} onChange={(e) => rename && setRename({ ...rename, name: e.target.value })} maxLength={24} className="w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-white" autoFocus />
      </Modal>
      <Modal
        open={!!kick}
        title={`Kick ${kick?.name}?`}
        onClose={() => setKick(null)}
        danger
        confirmLabel="Kick"
        onConfirm={async () => {
          const k = kick!;
          setKick(null);
          await call(`teams/${k.id}/kick`);
        }}
      >
        They leave the game and drop off the leaderboard. Their device token stops working.
      </Modal>
      <Modal open={!!rejoin} title={`Rejoin code for ${rejoin?.name}`} onClose={() => setRejoin(null)}>
        <p>On the new computer, open the join page, choose &ldquo;Use a rejoin code&rdquo; and type:</p>
        <p className="my-4 text-center font-mono text-4xl font-black tracking-widest text-white">{rejoin?.code}</p>
        <p className="text-xs text-ink-400">Works once, for 15 minutes. The old computer is signed out when it&apos;s used.</p>
      </Modal>
    </div>
  );
}
