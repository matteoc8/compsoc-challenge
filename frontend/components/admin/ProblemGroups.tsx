"use client";
// Groups are the sections of the public Problems page (e.g. one event's problems). The manager
// adds, renames, reorders and deletes them; FeatureModal puts quiz questions into one.

import { useCallback, useEffect, useState } from "react";
import type { ProblemGroup } from "@/components/site/problems";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";

const inputCls = "w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-white focus:border-round-blue focus:outline-none";

export function useGroups() {
  const [groups, setGroups] = useState<ProblemGroup[]>([]);
  const reload = useCallback(() => api<ProblemGroup[]>("/featured-groups").then(setGroups), []);
  useEffect(() => {
    reload().catch(() => {});
  }, [reload]);
  return { groups, setGroups, reload };
}

export function GroupSelect({ groups, value, onChange, className = "" }: { groups: ProblemGroup[]; value: string | null; onChange: (id: string | null) => void; className?: string }) {
  return (
    <select className={`${inputCls} ${className}`} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">No group</option>
      {groups.map((g) => (
        <option key={g.id} value={g.id}>
          {g.name}
        </option>
      ))}
    </select>
  );
}

function GroupRow({ g, first, last, onMove, onSaved, onDelete }: { g: ProblemGroup; first: boolean; last: boolean; onMove: (d: -1 | 1) => void; onSaved: (g: ProblemGroup) => void; onDelete: () => void }) {
  const [name, setName] = useState(g.name);
  const [description, setDescription] = useState(g.description);
  const dirty = name !== g.name || description !== g.description;
  return (
    <li className="space-y-1.5 rounded-md bg-ink-900 p-2.5 ring-1 ring-ink-600">
      <div className="flex gap-1.5">
        <input className={inputCls} value={name} maxLength={60} aria-label="Group name" onChange={(e) => setName(e.target.value)} />
        <Button size="sm" variant="secondary" disabled={first} onClick={() => onMove(-1)} aria-label={`Move ${g.name} up`}>
          ↑
        </Button>
        <Button size="sm" variant="secondary" disabled={last} onClick={() => onMove(1)} aria-label={`Move ${g.name} down`}>
          ↓
        </Button>
      </div>
      <input className={inputCls} value={description} maxLength={500} placeholder="Description (optional)" aria-label="Group description" onChange={(e) => setDescription(e.target.value)} />
      <div className="flex justify-end gap-1.5">
        {dirty && (
          <Button size="sm" disabled={!name.trim()} onClick={() => api<ProblemGroup>(`/featured-groups/${g.id}`, { method: "PUT", body: { name, description } }).then(onSaved)}>
            Save
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onDelete}>
          Delete
        </Button>
      </div>
    </li>
  );
}

/** Add, rename, reorder and delete groups. Deleting a group keeps its problems, ungrouped. */
export function GroupsManager({ open, onClose, groups, setGroups, onChanged }: { open: boolean; onClose: () => void; groups: ProblemGroup[]; setGroups: (g: ProblemGroup[]) => void; onChanged?: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  const move = (i: number, d: -1 | 1) =>
    run(async () => {
      const ids = groups.map((g) => g.id);
      [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
      setGroups(await api<ProblemGroup[]>("/featured-groups/order", { method: "PUT", body: { group_ids: ids } }));
    });
  return (
    <Modal open={open} title="Problem groups" onClose={onClose}>
      <p className="mb-3 text-ink-300">Each group is a section of the Problems page, in this order. Problems without a group are listed last.</p>
      {error && (
        <p className="mb-2 rounded bg-fail/15 p-2 text-fail" role="alert">
          {error}
        </p>
      )}
      <ul className="max-h-[50vh] space-y-2 overflow-y-auto">
        {groups.map((g, i) => (
          <GroupRow
            key={g.id + g.name + g.description}
            g={g}
            first={i === 0}
            last={i === groups.length - 1}
            onMove={(d) => move(i, d)}
            onSaved={(saved) => run(async () => setGroups(groups.map((x) => (x.id === saved.id ? saved : x))))}
            onDelete={() =>
              window.confirm(`Delete the group "${g.name}"? Its problems stay, without a group.`) &&
              run(async () => {
                await api(`/featured-groups/${g.id}`, { method: "DELETE" });
                setGroups(groups.filter((x) => x.id !== g.id));
              })
            }
          />
        ))}
      </ul>
      <form
        className="mt-3 flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const g = await api<ProblemGroup>("/featured-groups", { body: { name } });
            setGroups([...groups, g]);
            setName("");
          });
        }}
      >
        <input className={inputCls} value={name} maxLength={60} placeholder="New group, e.g. CompSoc 10/12" aria-label="New group name" onChange={(e) => setName(e.target.value)} />
        <Button size="sm" type="submit" disabled={!name.trim()}>
          Add
        </Button>
      </form>
    </Modal>
  );
}

/** Feature quiz questions on the Problems page: one question, or every coding question in a quiz. */
export function FeatureModal({ open, onClose, path, what, onDone }: { open: boolean; onClose: () => void; path: string; what: string; onDone: (msg: string) => void }) {
  const { groups, setGroups, reload } = useGroups();
  const [groupId, setGroupId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [publish, setPublish] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) reload().catch(() => {});
  }, [open, reload]);

  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      let gid = groupId;
      if (gid === "new") {
        const g = await api<ProblemGroup>("/featured-groups", { body: { name: newName } });
        setGroups([...groups, g]);
        gid = g.id;
      }
      const r = await api<{ created?: number }>(path, { body: { group_id: gid, published: publish } });
      const n = r.created ?? 1;
      onDone(`${n} problem${n === 1 ? "" : "s"} added to Featured problems${publish ? " and published" : " as drafts"}.`);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} title={`Feature ${what} on the site`} onClose={onClose} onConfirm={go} confirmLabel="Feature" busy={busy || (groupId === "new" && !newName.trim())}>
      <p className="mb-3 text-ink-300">Copies the problem text, examples and reference solution into Featured problems. Editing it there doesn&apos;t change the quiz.</p>
      <label className="block font-semibold text-white">
        Group
        <select className={`${inputCls} mt-1`} value={groupId ?? ""} onChange={(e) => setGroupId(e.target.value || null)}>
          <option value="">No group</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
          <option value="new">+ New group…</option>
        </select>
      </label>
      {groupId === "new" && <input className={`${inputCls} mt-2`} value={newName} maxLength={60} placeholder="e.g. CompSoc 10/12" aria-label="New group name" autoFocus onChange={(e) => setNewName(e.target.value)} />}
      <label className="mt-3 flex items-center gap-2 text-white">
        <input type="checkbox" checked={publish} onChange={(e) => setPublish(e.target.checked)} />
        Publish straight away <span className="text-ink-400">(otherwise drafts, to check first)</span>
      </label>
      {error && (
        <p className="mt-2 rounded bg-fail/15 p-2 text-fail" role="alert">
          {error}
        </p>
      )}
    </Modal>
  );
}
