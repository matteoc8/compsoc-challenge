"use client";
// Featured problems: what the public Problems section shows. Drafts stay hidden until published.

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { TestsTable } from "@/components/editor/TestsTable";
import { DifficultyBadge, type Difficulty, type FeaturedSummary } from "@/components/site/problems";
import { AdminNav } from "@/components/admin/AdminNav";
import { GroupSelect, GroupsManager, useGroups } from "@/components/admin/ProblemGroups";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { useAdmin } from "@/lib/admin";
import type { IOCase } from "@/lib/types";

const CodeEditor = dynamic(() => import("@/components/workspace/CodeEditor"), { ssr: false, loading: () => <div className="h-56 rounded bg-[#1e1e1e]" /> });

interface Featured extends FeaturedSummary {
  description_md: string;
  examples: IOCase[];
  solution_code: string;
  solution_md: string;
  published: boolean;
  updated_at: string;
}

const inputCls = "w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none";

function body(p: Featured) {
  const { title, difficulty, description_md, examples, solution_code, solution_md, credit, published, group_id } = p;
  return { title, difficulty, description_md, examples, solution_code, solution_md, credit, published, group_id };
}

function FeaturedEditor() {
  const me = useAdmin();
  const router = useRouter();
  const params = useSearchParams();
  const [list, setList] = useState<Featured[]>([]);
  const [draft, setDraft] = useState<Featured | null>(null);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [managing, setManaging] = useState(false);
  const { groups, setGroups } = useGroups();
  const selected = params.get("id");

  const load = useCallback(async () => {
    const rows = await api<Featured[]>("/featured");
    setList(rows);
    return rows;
  }, []);

  useEffect(() => {
    if (!me) return;
    load()
      .then((rows) => {
        const pick = rows.find((x) => x.id === selected) ?? rows[0] ?? null;
        setDraft(pick);
        setDirty(false);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load"));
  }, [me, load, selected]);

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const edit = (patch: Partial<Featured>) => {
    if (!draft) return;
    setDraft({ ...draft, ...patch });
    setDirty(true);
  };

  const save = (patch: Partial<Featured> = {}) =>
    act("save", async () => {
      const saved = await api<Featured>(`/featured/${draft!.id}`, { method: "PUT", body: body({ ...draft!, ...patch }) });
      setDraft(saved);
      setDirty(false);
      setList(list.map((x) => (x.id === saved.id ? saved : x)));
    });

  const open = (id: string) => {
    if (dirty && !window.confirm("Discard unsaved changes?")) return;
    router.replace(`/admin/featured?id=${id}`);
  };

  if (!me) return null;
  return (
    <main className="mx-auto min-h-full max-w-6xl p-6">
      <AdminNav me={me} />
      {error && (
        <div className="mb-4 rounded-md bg-fail/15 p-3 text-sm text-fail" role="alert">
          {error}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-[280px_1fr]">
        <aside>
          <div className="mb-3 flex gap-2">
          <Button
            className="flex-1"
            disabled={!!busy}
            onClick={() =>
              act("new", async () => {
                const p = await api<Featured>("/featured", { body: { title: "New problem" } });
                await load();
                router.replace(`/admin/featured?id=${p.id}`);
              })
            }
          >
            + New problem
          </Button>
          <Button variant="secondary" onClick={() => setManaging(true)}>
            Groups…
          </Button>
          </div>
          {[...groups.map((g) => ({ id: g.id as string | null, name: g.name })), { id: null, name: groups.length ? "No group" : "" }].map((sec) => {
            const items = list.filter((p) => (p.group_id ?? null) === sec.id);
            if (!items.length) return null;
            return (
              <div key={sec.id ?? "none"} className="mb-3">
                {sec.name && <h3 className="mb-1 px-1 text-xs font-bold uppercase tracking-wide text-ink-400">{sec.name}</h3>}
                <ul className="space-y-1.5">
                  {items.map((p) => (
                    <li key={p.id}>
                      <button onClick={() => open(p.id)} className={`w-full rounded-md px-3 py-2 text-left ${p.id === draft?.id ? "bg-ink-600" : "bg-ink-800 hover:bg-ink-700"}`}>
                        <div className="truncate text-sm font-semibold text-white">{p.title}</div>
                        <div className="flex items-center gap-2 text-xs">
                          <DifficultyBadge d={p.difficulty} />
                          <span className={p.published ? "text-pass" : "text-ink-400"}>{p.published ? "published" : "draft"}</span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
          {!list.length && <p className="rounded-md bg-ink-800 p-3 text-sm text-ink-400">No featured problems yet. Start one here, or feature a submitted problem or a quiz question.</p>}
        </aside>

        {draft && (
          <section key={draft.id} className="space-y-5 rounded-lg bg-ink-800 p-5 ring-1 ring-ink-600">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded px-2 py-1 text-xs font-bold ${draft.published ? "bg-pass/20 text-pass" : "bg-ink-600 text-ink-300"}`}>
                {draft.published ? "Published: on the Problems page" : "Draft: only you can see it"}
              </span>
              <span className="text-xs text-ink-400" role="status">
                {busy === "save" ? "Saving…" : dirty ? "Unsaved changes" : "Saved"}
              </span>
              <div className="ml-auto flex flex-wrap gap-2">
                {draft.published && (
                  <a href={`/problems/${draft.id}`} target="_blank" rel="noreferrer" className="rounded-md bg-ink-600 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:bg-ink-500">
                    View on site ↗
                  </a>
                )}
                <Button size="sm" variant="secondary" disabled={!!busy || !dirty} onClick={() => save()}>
                  Save
                </Button>
                <Button size="sm" variant={draft.published ? "secondary" : "success"} disabled={!!busy || !draft.title.trim()} onClick={() => save({ published: !draft.published })}>
                  {draft.published ? "Unpublish" : "Save & publish"}
                </Button>
                <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => setConfirmDelete(true)}>
                  Delete
                </Button>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-[1.4fr_130px_1fr_1fr]">
              <label className="block text-sm font-semibold text-white">
                Title
                <input className={`${inputCls} mt-1`} value={draft.title} maxLength={120} onChange={(e) => edit({ title: e.target.value })} />
              </label>
              <label className="block text-sm font-semibold text-white">
                Difficulty
                <select className={`${inputCls} mt-1`} value={draft.difficulty} onChange={(e) => edit({ difficulty: e.target.value as Difficulty })}>
                  <option value="easy">Easy</option>
                  <option value="medium">Medium</option>
                  <option value="hard">Hard</option>
                </select>
              </label>
              <label className="block text-sm font-semibold text-white">
                Credit <span className="font-normal text-ink-400">(optional)</span>
                <input className={`${inputCls} mt-1`} value={draft.credit ?? ""} maxLength={80} placeholder="e.g. Submitted by Sam Smith" onChange={(e) => edit({ credit: e.target.value })} />
              </label>
              <label className="block text-sm font-semibold text-white">
                Group
                <GroupSelect className="mt-1" groups={groups} value={draft.group_id} onChange={(group_id) => edit({ group_id })} />
              </label>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="block text-sm font-semibold text-white">
                Problem <span className="font-normal text-ink-400">(Markdown)</span>
                <textarea className={`${inputCls} mt-1 min-h-[200px] font-mono text-xs`} value={draft.description_md} onChange={(e) => edit({ description_md: e.target.value })} />
              </label>
              <div>
                <span className="mb-1 block text-sm font-semibold text-white">Preview</span>
                <div className="min-h-[200px] rounded border border-ink-600 bg-ink-900 p-3 text-sm text-ink-200">
                  <Markdown>{draft.description_md}</Markdown>
                </div>
              </div>
            </div>
            <TestsTable label="Examples" rows={draft.examples} onChange={(examples) => edit({ examples })} max={10} hint="shown with the problem" />
            <fieldset className="space-y-4 rounded-md border border-ink-600 p-4">
              <legend className="px-1 text-sm font-semibold text-white">Solution (hidden until someone clicks Show solution)</legend>
              <label className="block text-sm font-semibold text-white">
                Explanation <span className="font-normal text-ink-400">(Markdown, optional)</span>
                <textarea className={`${inputCls} mt-1 min-h-[100px] font-mono text-xs`} value={draft.solution_md} onChange={(e) => edit({ solution_md: e.target.value })} />
              </label>
              <div>
                <span className="mb-1 block text-sm font-semibold text-white">Code</span>
                <div className="h-56 overflow-hidden rounded border border-ink-600">
                  <CodeEditor value={draft.solution_code} onChange={(v) => edit({ solution_code: v })} ariaLabel="Solution code" />
                </div>
              </div>
            </fieldset>
          </section>
        )}
      </div>
      <GroupsManager open={managing} onClose={() => setManaging(false)} groups={groups} setGroups={setGroups} onChanged={() => void load()} />
      <Modal
        open={confirmDelete}
        title={`Delete "${draft?.title}"?`}
        onClose={() => setConfirmDelete(false)}
        danger
        confirmLabel="Delete"
        onConfirm={() => {
          setConfirmDelete(false);
          void act("delete", async () => {
            await api(`/featured/${draft!.id}`, { method: "DELETE" });
            const rows = await load();
            setDraft(rows[0] ?? null);
            setDirty(false);
            router.replace("/admin/featured");
          });
        }}
      >
        It disappears from the Problems page straight away. This can&apos;t be undone.
      </Modal>
    </main>
  );
}

export default function FeaturedPage() {
  return (
    <Suspense>
      <FeaturedEditor />
    </Suspense>
  );
}
