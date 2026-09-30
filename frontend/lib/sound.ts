"use client";
// Projector sounds, synthesised with Web Audio (no sound files, nothing copied from Kahoot).
// Browsers block audio until a user gesture, hence the "Start presentation" click.

let ctx: AudioContext | null = null;
let muted = false;

export function unlockAudio() {
  try {
    ctx = ctx || new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    if (ctx.state === "suspended") void ctx.resume();
  } catch {
    ctx = null;
  }
}

export function setMuted(m: boolean) {
  muted = m;
}

function tone(freq: number, start: number, dur: number, type: OscillatorType = "sine", gain = 0.15) {
  if (!ctx || muted) return;
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = type;
  o.frequency.value = freq;
  g.gain.setValueAtTime(0, ctx.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  o.connect(g).connect(ctx.destination);
  o.start(ctx.currentTime + start);
  o.stop(ctx.currentTime + start + dur + 0.05);
}

export function tick(final = false) {
  tone(final ? 880 : 660, 0, 0.08, "square", 0.08);
}

export function sting() {
  [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.07, 0.25, "triangle", 0.12));
}

export function buzzer() {
  tone(196, 0, 0.5, "sawtooth", 0.1);
  tone(147, 0.05, 0.6, "sawtooth", 0.08);
}
