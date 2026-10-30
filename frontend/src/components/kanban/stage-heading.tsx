"use client";

import { Info, Pencil, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { updateStage, type StageRow } from "@/lib/api";
import type { Stage } from "@/lib/types";

export type StageDefinitionPatch = { title: string; color: string; description: string };
type Placement = { left: number; width: number; top?: number; bottom?: number; maxHeight: number };

function titleInk(color: string) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return undefined;
  const rgb = [1, 3, 5].map((start) => {
    const value = parseInt(color.slice(start, start + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] > 0.179 ? "#111827" : "#ffffff";
}

function StageEditor({ stage, onSaved, onClose, placement }: {
  stage: Stage;
  onSaved: (patch: StageDefinitionPatch) => void;
  onClose: () => void;
  placement: { left: number; top: number; width: number };
}) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true);
  const pending = useRef(false);
  const titleId = useId();
  const [draft, setDraft] = useState<StageDefinitionPatch>({ title: stage.title, color: stage.color, description: stage.description ?? "" });
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    alive.current = true;
    const element = dialog.current;
    element?.showModal();
    const controller = new AbortController();
    // The existing stage list also materializes the canonical stages on a fresh installation.
    void fetch("/api/sales/stages", { cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("load");
      const rows: unknown = await response.json();
      if (!Array.isArray(rows)) throw new Error("load");
      const row = rows.find((value: StageRow) => value?.code === stage.id);
      if (!row || typeof row.title !== "string" || typeof row.color !== "string"
        || (row.description !== undefined && typeof row.description !== "string")) throw new Error("load");
      if (alive.current && !controller.signal.aborted) {
        setDraft({ title: row.title, color: row.color, description: row.description ?? "" });
        setReady(true);
      }
    }).catch(() => {
      if (alive.current && !controller.signal.aborted) setError("Не удалось загрузить стадию. Закройте окно и попробуйте снова.");
    });
    return () => {
      alive.current = false;
      controller.abort();
      element?.close();
    };
  }, [stage.id]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!ready || pending.current || !draft.title.trim()) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const patch = { ...draft, title: draft.title.trim() };
    let confirmed = false;
    try { confirmed = await updateStage(stage.id, patch); } catch { /* Keep the draft on an uncertain response. */ }
    pending.current = false;
    if (!alive.current) return;
    if (!confirmed) {
      setBusy(false);
      setError("Сохранение не подтверждено. Текст оставлен в форме. Проверьте доступ и состояние стадии перед повтором.");
      return;
    }
    onSaved(patch);
    onClose();
    router.refresh();
  }

  return <dialog ref={dialog} aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); if (!pending.current) onClose(); }}
    className="fixed max-h-[calc(100vh-24px)] overflow-y-auto rounded-2xl border border-line bg-surface p-0 text-ink shadow-pop backdrop:bg-black/20"
    style={{ ...placement, margin: 0, maxHeight: `calc(100dvh - ${placement.top + 12}px)` }}>
    <div className="h-1" style={{ backgroundColor: draft.color }} />
    <form onSubmit={(event) => void save(event)} className="space-y-4 p-5 text-sm font-normal">
      <div className="flex items-center justify-between gap-3">
        <h2 id={titleId} className="text-lg font-bold">Стадия</h2>
        <label className="relative ml-auto flex cursor-pointer items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-muted">
          <span aria-hidden className="h-4 w-4 rounded-full border border-line" style={{ backgroundColor: draft.color }} />
          Оформление
          <input type="color" aria-label="Цвет стадии" disabled={!ready || busy}
            value={/^#[0-9a-f]{6}$/i.test(draft.color) ? draft.color : "#64748B"}
            onChange={(event) => setDraft({ ...draft, color: event.target.value })}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-default" />
        </label>
        <button type="button" disabled={busy} aria-label="Закрыть редактор стадии" onClick={onClose} className="rounded p-1 text-muted hover:bg-sunken disabled:opacity-50"><X size={18} /></button>
      </div>
      {!ready && !error && <p role="status">Загрузка стадии…</p>}
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
      <fieldset disabled={!ready || busy} className="space-y-3">
        <label className="block"><span className="mb-1 block text-muted">Название стадии</span>
          <input required maxLength={128} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            style={{ backgroundColor: draft.color, color: titleInk(draft.color) }}
            className="w-full rounded-lg border border-line px-3 py-3 font-semibold" />
        </label>
        <label className="block"><span className="mb-1 block text-muted">Описание стадии</span>
          <textarea rows={5} maxLength={2000} value={draft.description}
            placeholder="Когда переводить сюда сделку и что нужно проверить"
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            className="w-full resize-y rounded-lg border border-line bg-canvas px-3 py-2 leading-relaxed" />
        </label>
        <p className="text-xs text-muted">Описание видно в подсказке у названия стадии.</p>
      </fieldset>
      <div className="flex gap-3">
        <button type="submit" disabled={!ready || busy || !draft.title.trim()} className="rounded-lg bg-accent px-4 py-2 font-semibold text-white disabled:opacity-50">{busy ? "Сохранение…" : "Сохранить"}</button>
        <button type="button" disabled={busy} onClick={onClose} className="rounded-lg px-3 py-2 text-muted hover:bg-sunken disabled:opacity-50">Отмена</button>
      </div>
    </form>
  </dialog>;
}

export function StageHeading({ stage, onSaved }: { stage: Stage; onSaved: (patch: StageDefinitionPatch) => void }) {
  const trigger = useRef<HTMLButtonElement>(null);
  const pencil = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const panel = useRef<HTMLDivElement>(null);
  const pinned = useRef(false);
  const focused = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tipId = useId();
  const [tip, setTip] = useState<Placement | null>(null);
  const [editor, setEditor] = useState<{ left: number; top: number; width: number } | null>(null);
  const description = stage.description?.trim() ?? "";

  useEffect(() => {
    if (editor) restoreFocus.current = true;
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      pencil.current?.focus();
    }
  }, [editor]);

  function cancelClose() { if (timer.current) clearTimeout(timer.current); }
  function leave() {
    cancelClose();
    timer.current = setTimeout(() => { if (!pinned.current && !focused.current) setTip(null); }, 160);
  }
  function show() {
    cancelClose();
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect || !description) return;
    const width = Math.min(360, window.innerWidth - 24);
    const below = window.innerHeight - rect.bottom >= 160;
    setTip({ width, left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
      ...(below ? { top: rect.bottom + 10 } : { bottom: window.innerHeight - rect.top + 10 }),
      maxHeight: Math.max(80, Math.min(300, below ? window.innerHeight - rect.bottom - 24 : rect.top - 24)) });
  }

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => {
    if (!tip) return;
    const dismiss = () => { pinned.current = false; setTip(null); };
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !trigger.current?.contains(event.target) && !panel.current?.contains(event.target)) dismiss();
    };
    const scroll = (event: Event) => { if (!(event.target instanceof Node) || !panel.current?.contains(event.target)) dismiss(); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") dismiss(); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", dismiss);
    };
  }, [tip]);

  return <div className="flex min-w-0 flex-1 items-center gap-1">
    {description ? <button ref={trigger} type="button" aria-label={`Описание стадии «${stage.title}»`}
      aria-describedby={tip ? tipId : undefined} onMouseEnter={show} onMouseLeave={leave}
      onFocus={() => { focused.current = true; show(); }} onBlur={() => { focused.current = false; leave(); }}
      onClick={() => { pinned.current = !pinned.current; if (pinned.current) show(); else setTip(null); }}
      className="flex min-w-0 items-center gap-1 rounded text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      <span className="truncate">{stage.title}</span><Info size={13} className="shrink-0 text-muted" />
    </button> : <span className="truncate">{stage.title}</span>}
    <button ref={pencil} type="button" aria-label={`Редактировать стадию «${stage.title}»`}
      onClick={() => {
        pinned.current = false;
        setTip(null);
        const rect = pencil.current?.getBoundingClientRect();
        if (!rect) return;
        const width = Math.min(440, window.innerWidth - 24);
        setEditor({ width, left: Math.max(12, Math.min(rect.left - width / 2, window.innerWidth - width - 12)),
          top: Math.max(12, Math.min(rect.bottom + 10, window.innerHeight - 560)) });
      }} className="shrink-0 rounded p-1 text-faint hover:bg-sunken hover:text-accent-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      <Pencil size={13} />
    </button>
    {tip && description && createPortal(<div ref={panel} id={tipId} role="tooltip" onMouseEnter={cancelClose} onMouseLeave={leave}
      className="fixed z-[100] rounded-2xl bg-accent p-4 text-sm font-normal leading-relaxed text-white shadow-pop"
      style={{ left: tip.left, top: tip.top, bottom: tip.bottom, width: tip.width }}>
      <span aria-hidden className="absolute left-6 h-3 w-3 rotate-45 bg-accent" style={tip.top !== undefined ? { top: -5 } : { bottom: -5 }} />
      <p className="overflow-y-auto whitespace-pre-wrap break-words" style={{ maxHeight: tip.maxHeight }}>{description}</p>
    </div>, document.body)}
    {editor && <StageEditor stage={stage} placement={editor} onSaved={onSaved} onClose={() => setEditor(null)} />}
  </div>;
}
