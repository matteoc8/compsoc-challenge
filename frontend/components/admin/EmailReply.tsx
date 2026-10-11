"use client";
// Reply to whoever submitted a problem. With SMTP set up on the server it sends from the
// admin's account; otherwise it opens the admin's own mail app with the message filled in.

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";

export interface ReplyTo {
  id: string;
  author_name: string;
  email: string | null;
  title: string;
  status: "pending" | "accepted" | "rejected";
}

type Template = "accepted" | "featured" | "rejected" | "blank";

function draft(t: Template, p: ReplyTo): { subject: string; body: string } {
  const first = p.author_name.split(" ")[0];
  const subject = `Your CompSoc problem: ${p.title}`;
  const sign = "\n\nThanks,\nCompSoc";
  if (t === "accepted")
    return { subject, body: `Hi ${first},\n\nGood news: your problem "${p.title}" has been accepted and we're planning to use it in a CompSoc Challenge. Thanks for sending it in!${sign}` };
  if (t === "featured")
    return { subject, body: `Hi ${first},\n\nGreat news: your problem "${p.title}" is now a featured problem on the CompSoc site, with your name on it.${sign}` };
  if (t === "rejected")
    return {
      subject,
      body: `Hi ${first},\n\nThanks for sending in "${p.title}". We won't be using it this time, but please keep the ideas coming. Problems with a clear input/output format and a couple of examples are the easiest to use.${sign}`,
    };
  return { subject, body: `Hi ${first},\n\n${sign}` };
}

export function EmailReply({ problem, onClose, onSent }: { problem: ReplyTo; onClose: () => void; onSent: () => void }) {
  const [status, setStatus] = useState<{ configured: boolean; from: string | null } | null>(null);
  const [template, setTemplate] = useState<Template>(problem.status === "rejected" ? "rejected" : "accepted");
  const [msg, setMsg] = useState(() => draft(problem.status === "rejected" ? "rejected" : "accepted", problem));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ configured: boolean; from: string | null }>("/email/status")
      .then(setStatus)
      .catch(() => setStatus({ configured: false, from: null }));
  }, []);

  const pick = (t: Template) => {
    setTemplate(t);
    setMsg(draft(t, problem));
  };

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/problem-submissions/${problem.id}/email`, { body: msg });
      onSent();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const mailto = `mailto:${encodeURIComponent(problem.email ?? "")}?subject=${encodeURIComponent(msg.subject)}&body=${encodeURIComponent(msg.body)}`;
  const input = "w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal aria-label="Email reply" onClick={onClose}>
      <div className="w-full max-w-xl space-y-3 rounded-xl bg-ink-800 p-5 shadow-2xl ring-1 ring-ink-600" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-stage text-xl font-black text-white">Email {problem.author_name}</h2>
        <p className="text-sm text-ink-300">
          To <b className="text-white">{problem.email}</b>
          {status?.configured && (
            <>
              {" "}
              from <b className="text-white">{status.from}</b>
            </>
          )}
        </p>
        <div className="flex flex-wrap gap-1">
          {(["accepted", "featured", "rejected", "blank"] as const).map((t) => (
            <button key={t} onClick={() => pick(t)} className={`rounded px-2.5 py-1 text-xs font-semibold capitalize ${template === t ? "bg-round-blue text-white" : "bg-ink-700 text-ink-300 hover:bg-ink-600"}`}>
              {t}
            </button>
          ))}
        </div>
        <label className="block text-sm text-ink-200">
          Subject
          <input className={`${input} mt-1`} value={msg.subject} maxLength={200} onChange={(e) => setMsg({ ...msg, subject: e.target.value })} />
        </label>
        <label className="block text-sm text-ink-200">
          Message
          <textarea className={`${input} mt-1 min-h-[180px]`} value={msg.body} maxLength={10000} onChange={(e) => setMsg({ ...msg, body: e.target.value })} />
        </label>
        {error && <p className="text-sm text-fail">{error}</p>}
        {status && !status.configured && (
          <p className="rounded bg-ink-700 p-2 text-xs text-ink-300">
            Sending straight from the site isn&apos;t set up (see SMTP in the README), so this opens your own email app with the message ready. Press <b>I&apos;ve sent it</b> afterwards to mark it as replied.
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          {status?.configured ? (
            <Button disabled={busy || !msg.subject.trim() || !msg.body.trim()} onClick={send}>
              {busy ? "Sending…" : "Send email"}
            </Button>
          ) : (
            <>
              <a href={mailto} className="rounded-md bg-round-blue px-4 py-2 text-sm font-semibold text-white hover:brightness-110">
                Open in my email app
              </a>
              <Button
                variant="secondary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api(`/problem-submissions/${problem.id}/emailed`, { method: "POST" });
                    onSent();
                    onClose();
                  } catch (e) {
                    setError(e instanceof ApiError ? e.message : String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                I&apos;ve sent it
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
