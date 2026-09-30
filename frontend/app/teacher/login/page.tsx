"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { TeacherMe } from "@/lib/teacher";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(false);
  const [current, setCurrent] = useState("");
  const [next1, setNext1] = useState("");
  const [next2, setNext2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<TeacherMe>("/auth/me")
      .then((m) => (m.must_change_password ? setMustChange(true) : router.replace("/teacher")))
      .catch(() => undefined);
  }, [router]);

  const login = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api<TeacherMe>("/auth/login", { body: { username, password } });
      if (me.must_change_password) {
        setMustChange(true);
        setCurrent(password);
      } else router.replace("/teacher");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  const change = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next1 !== next2) {
      setError("The new passwords don't match");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/auth/change-password", { body: { current_password: current, new_password: next1 } });
      router.replace("/teacher");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the password");
    } finally {
      setBusy(false);
    }
  };

  const input = "w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-white focus:border-round-blue focus:outline-none";
  return (
    <main className="flex min-h-full items-center justify-center bg-ink-900 p-4">
      <div className="w-full max-w-sm rounded-xl bg-ink-800 p-6 shadow-2xl ring-1 ring-ink-600">
        <h1 className="mb-1 font-stage text-2xl font-black text-white">Teacher login</h1>
        <p className="mb-5 text-sm text-ink-400">CompSoc Challenge</p>
        {!mustChange ? (
          <form onSubmit={login} className="space-y-3">
            <label className="block text-sm">
              Username
              <input className={input} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
            </label>
            <label className="block text-sm">
              Password
              <input className={input} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
            {error && (
              <p className="text-sm font-semibold text-fail" role="alert">
                {error}
              </p>
            )}
            <button disabled={busy} className="w-full rounded-md bg-round-blue py-2 font-bold text-white disabled:opacity-50">
              {busy ? "Logging in…" : "Log in"}
            </button>
          </form>
        ) : (
          <form onSubmit={change} className="space-y-3">
            <p className="rounded-md bg-round-yellow/15 p-3 text-sm text-round-yellow">Choose your own password before continuing (at least 10 characters).</p>
            <label className="block text-sm">
              Current password
              <input className={input} type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
            </label>
            <label className="block text-sm">
              New password
              <input className={input} type="password" value={next1} onChange={(e) => setNext1(e.target.value)} autoComplete="new-password" minLength={10} required />
            </label>
            <label className="block text-sm">
              Repeat new password
              <input className={input} type="password" value={next2} onChange={(e) => setNext2(e.target.value)} autoComplete="new-password" minLength={10} required />
            </label>
            {error && (
              <p className="text-sm font-semibold text-fail" role="alert">
                {error}
              </p>
            )}
            <button disabled={busy} className="w-full rounded-md bg-round-green py-2 font-bold text-white disabled:opacity-50">
              {busy ? "Saving…" : "Save and continue"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
