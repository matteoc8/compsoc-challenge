"use client";
import { useEffect, type ReactNode } from "react";
import { Button } from "./Button";

export function Modal({
  open,
  title,
  children,
  onClose,
  onConfirm,
  confirmLabel = "Confirm",
  danger = false,
  busy = false,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  onClose: () => void;
  onConfirm?: () => void;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-md rounded-xl bg-ink-800 p-5 shadow-2xl ring-1 ring-ink-600" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-3 text-lg font-bold text-white">{title}</h2>
        <div className="mb-5 text-sm text-ink-200">{children}</div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {onConfirm ? "Cancel" : "Close"}
          </Button>
          {onConfirm && (
            <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy} autoFocus>
              {confirmLabel}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
