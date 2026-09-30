"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, ApiError, getTeamToken, setTeamToken } from "@/lib/api";
import { BRAND } from "@/lib/brand";

function JoinForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [code, setCode] = useState(params.get("code")?.toUpperCase() ?? "");
  const [name, setName] = useState("");
  const [rejoin, setRejoin] = useState("");
  const [mode, setMode] = useState<"join" | "rejoin">("join");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [existing, setExisting] = useState<{ name: string } | null>(null);

  // Reopening the site goes straight back into the game.
  useEffect(() => {
    const token = getTeamToken();
    if (!token) return;
    api<{ name: string }>("/team/me", { token })
      .then((me) => setExisting(me))
      .catch(() => setTeamToken(null));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = mode === "join" ? { code: code.trim(), team_name: name.trim() } : { rejoin_code: rejoin.trim() };
      const r = await api<{ token: string }>("/join", { body });
      setTeamToken(r.token);
      router.push("/play");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't join");
    } finally {
      setBusy(false);
    }
  };

  const input =
    "w-full rounded-lg border-2 border-transparent bg-white px-4 py-3 text-center font-stage text-2xl font-extrabold text-stage-deep placeholder:text-black/35 focus:border-accent focus:outline-none";
  return (
    <main className="stage-bg flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <h1 className="whitespace-nowrap font-stage text-4xl font-black text-white">{BRAND.event}</h1>
        </div>
        {existing && (
          <div className="mb-4 rounded-lg bg-black/30 p-4 text-center text-white">
            <p className="font-stage font-bold">You&apos;re already in as {existing.name}.</p>
            <button onClick={() => router.push("/play")} className="mt-3 w-full rounded-lg bg-round-green py-3 font-stage text-xl font-black text-white">
              Back to the game
            </button>
          </div>
        )}
        <form onSubmit={submit} className="space-y-3 rounded-xl bg-black/20 p-5 shadow-2xl">
          {mode === "join" ? (
            <>
              <label className="sr-only" htmlFor="code">
                Game code
              </label>
              <input
                id="code"
                className={input}
                placeholder="Game code"
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                maxLength={6}
                autoComplete="off"
                autoCapitalize="characters"
                required
              />
              <label className="sr-only" htmlFor="team">
                Team name
              </label>
              <input id="team" className={input} placeholder="Team name" value={name} onChange={(e) => setName(e.target.value)} maxLength={24} autoComplete="off" required />
            </>
          ) : (
            <>
              <label className="sr-only" htmlFor="rejoin">
                Rejoin code
              </label>
              <input
                id="rejoin"
                className={input}
                placeholder="Rejoin code"
                value={rejoin}
                onChange={(e) => setRejoin(e.target.value.toUpperCase())}
                maxLength={8}
                autoComplete="off"
                required
              />
            </>
          )}
          {error && (
            <p className="rounded-md bg-fail px-3 py-2 text-center font-bold text-white" role="alert">
              {error}
            </p>
          )}
          <button disabled={busy} className="w-full rounded-lg bg-accent py-3 font-stage text-2xl font-black text-black shadow-lg hover:bg-accent-light disabled:opacity-60">
            {busy ? "Joining…" : mode === "join" ? "Enter" : "Rejoin"}
          </button>
        </form>
        <button onClick={() => setMode(mode === "join" ? "rejoin" : "join")} className="mt-4 w-full text-center font-stage text-sm font-bold text-white/80 hover:text-white">
          {mode === "join" ? "Moving to another computer? Use a rejoin code" : "Back to joining with a game code"}
        </button>
      </div>
    </main>
  );
}

export default function JoinPage() {
  return (
    <Suspense>
      <JoinForm />
    </Suspense>
  );
}
