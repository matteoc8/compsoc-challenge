"use client";

// useGameSocket: one WebSocket per screen with auto-reconnect (0.5 s → 5 s backoff),
// server clock offset from ping round-trips (median of the last 5), seq-gap detection,
// and a heartbeat: a dropped laptop network often leaves the TCP connection hanging
// silently, so a socket that hears nothing for 12 s is abandoned and replaced.

import { useEffect, useRef } from "react";
import { useGame } from "./store";
import type { WsMessage } from "./types";

const TERMINAL: Record<number, "unauthorised" | "replaced" | "ended"> = {
  4400: "unauthorised",
  4401: "unauthorised",
  4001: "replaced",
  4003: "ended",
};
const PING_EVERY_MS = 5_000;
const DEAD_AFTER_MS = 12_000;

export function wsUrl(params: Record<string, string>): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws?${new URLSearchParams(params).toString()}`;
}

export function useGameSocket(params: Record<string, string> | null, generation = 0) {
  const key = params ? JSON.stringify(params) : null;
  const sockRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!key) return;
    const p = JSON.parse(key) as Record<string, string>;
    const store = useGame.getState();
    let stopped = false;
    let delay = 500;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    const samples: number[] = [];

    const scheduleReconnect = (wait = delay) => {
      if (stopped) return;
      if (retry) clearTimeout(retry);
      useGame.getState().setStatus("reconnecting");
      retry = setTimeout(connect, wait);
      delay = Math.min(delay * 2, 5000);
    };

    // Drop a socket without waiting for a close handshake that may never come.
    const abandon = (ws: WebSocket | null) => {
      if (!ws) return;
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      try {
        ws.close();
      } catch {
        /* already closed */
      }
      if (sockRef.current === ws) sockRef.current = null;
      if (heartbeat) clearInterval(heartbeat);
      heartbeat = null;
    };

    function connect() {
      if (stopped) return;
      retry = null;
      abandon(sockRef.current);
      if (!useGame.getState().snapshot) store.setStatus("connecting");
      const ws = new WebSocket(wsUrl(p));
      sockRef.current = ws;
      let lastSeq = 0;
      let lastHeard = Date.now();
      let quickPings = 0;

      const ping = () => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping", data: { t0: Date.now() } }));
      };

      ws.onopen = () => {
        delay = 500;
        lastHeard = Date.now();
        store.setStatus("open");
        ping();
        heartbeat = setInterval(() => {
          if (Date.now() - lastHeard > DEAD_AFTER_MS) {
            abandon(ws);
            scheduleReconnect(0);
            return;
          }
          ping();
        }, PING_EVERY_MS);
      };
      ws.onmessage = (ev) => {
        lastHeard = Date.now();
        let m: WsMessage;
        try {
          m = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (lastSeq && m.seq !== lastSeq + 1 && m.type !== "snapshot") {
          ws.send(JSON.stringify({ type: "snapshot.request" }));
        }
        lastSeq = m.seq;
        if (m.type === "pong") {
          const t1 = Date.now();
          samples.push(m.data.server_ms + (t1 - m.data.t0) / 2 - t1);
          if (samples.length > 5) samples.shift();
          const sorted = [...samples].sort((a, b) => a - b);
          useGame.getState().setOffset(sorted[Math.floor(sorted.length / 2)]);
          if (++quickPings < 5) setTimeout(ping, 150);
          return;
        }
        useGame.getState().apply(m);
      };
      ws.onclose = (ev) => {
        if (heartbeat) clearInterval(heartbeat);
        heartbeat = null;
        if (sockRef.current === ws) sockRef.current = null;
        const terminal = TERMINAL[ev.code];
        if (terminal) {
          stopped = true;
          const cur = useGame.getState();
          // keep a more specific message set by session.replaced / session.ended
          if (cur.status !== terminal) cur.setStatus(terminal, ev.reason || null);
          return;
        }
        scheduleReconnect();
      };
      ws.onerror = () => ws.close();
    }

    connect();

    const onOffline = () => {
      abandon(sockRef.current);
      scheduleReconnect(1000);
    };
    const onWake = () => {
      // a laptop waking from sleep: reconnect straight away instead of waiting out the backoff
      if (stopped || document.visibilityState !== "visible" || sockRef.current) return;
      delay = 500;
      scheduleReconnect(0);
    };
    const onOnline = () => {
      if (stopped) return;
      delay = 500;
      scheduleReconnect(0);
    };
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    document.addEventListener("visibilitychange", onWake);
    return () => {
      stopped = true;
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
      document.removeEventListener("visibilitychange", onWake);
      if (retry) clearTimeout(retry);
      const ws = sockRef.current;
      abandon(ws);
    };
  }, [key, generation]);

  return sockRef;
}

/** Remaining ms on the server's clock, for rendering a countdown. */
export function remainingMs(game: { deadline: string | null; paused: boolean; remaining_ms: number | null }, offset: number): number | null {
  if (game.paused) return game.remaining_ms;
  if (!game.deadline) return null;
  return Math.max(0, Date.parse(game.deadline) - (Date.now() + offset));
}
