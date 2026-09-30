"use client";
import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Drag, paste or browse. The server decodes, strips metadata, resizes and re-encodes to WebP.
export function ImageDropZone({
  url,
  alt,
  onChange,
}: {
  url: string | null;
  alt: string | null;
  onChange: (patch: Partial<{ image_media_id: string | null; image_url: string | null; image_alt: string | null }>) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = async (file: File | undefined | null) => {
    if (!file) return;
    if (file.size > 5_000_000) {
      setError("Images must be 5 MB or smaller");
      return;
    }
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await api<{ id: string; url: string }>("/media", { form, method: "POST" });
      onChange({ image_media_id: r.id, image_url: r.url });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div
        tabIndex={0}
        role="button"
        aria-label="Question image: drop, paste or click to browse"
        onClick={() => fileRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileRef.current?.click()}
        onPaste={(e) => upload(Array.from(e.clipboardData.files)[0])}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void upload(e.dataTransfer.files[0]);
        }}
        className={`flex min-h-[96px] cursor-pointer items-center justify-center gap-4 rounded-md border-2 border-dashed p-3 text-sm ${over ? "border-round-blue bg-round-blue/10" : "border-ink-600 hover:border-ink-400"}`}
      >
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={alt || ""} className="max-h-28 rounded object-contain" />
        ) : null}
        <span className="text-ink-400">{busy ? "Uploading…" : url ? "Drop, paste or click to replace" : "Optional image: drop, paste or click (PNG, JPEG, WebP, GIF, ≤ 5 MB)"}</span>
      </div>
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
      {error && <p className="mt-1 text-xs text-fail">{error}</p>}
      {url && (
        <div className="mt-2 flex gap-2">
          <input
            value={alt ?? ""}
            onChange={(e) => onChange({ image_alt: e.target.value.slice(0, 200) })}
            placeholder="Alt text (describe the image)"
            className="flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-xs text-ink-200"
          />
          <button onClick={() => onChange({ image_media_id: null, image_url: null, image_alt: null })} className="rounded bg-ink-600 px-2 py-1 text-xs text-ink-200 hover:bg-ink-500">
            Remove
          </button>
        </div>
      )}
    </div>
  );
}
