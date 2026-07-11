"use client";

import { useEffect, useRef, useState } from "react";
import {
  deleteLeadAttachment,
  fetchLeadAttachments,
  leadAttachmentDownloadUrl,
  uploadLeadAttachment,
} from "@/lib/api";
import type { LeadAttachment } from "@/lib/types";

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  manual: { label: "вручную", cls: "bg-sunken text-muted" },
  email: { label: "с почты", cls: "bg-blue-100 text-blue-700" },
  tender: { label: "с тендера", cls: "bg-violet-100 text-violet-700" },
};

function iconFor(contentType: string): string {
  if (contentType.includes("pdf")) return "📄";
  if (contentType.includes("spreadsheet") || contentType.includes("xlsx") || contentType.includes("excel")) {
    return "📊";
  }
  if (contentType.includes("word") || contentType.includes("docx")) return "📝";
  if (contentType.startsWith("image/")) return "🖼";
  return "📎";
}

function formatSize(sizeBytes: number): string {
  const kb = sizeBytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} КБ`;
  return `${(kb / 1024).toFixed(1)} МБ`;
}

/**
 * Полоска вложений лида (сканы тендерных заявок, файлы писем, ручная загрузка).
 * Грузит список при монтировании; загрузка нового файла — без полного рефетча
 * (добавляем в локальный список сразу после успешного ответа).
 */
export function LeadAttachments({ leadId }: { leadId: number }) {
  const [attachments, setAttachments] = useState<LeadAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchLeadAttachments(leadId).then((list) => {
      if (!cancelled) {
        setAttachments(list);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [leadId]);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    const result = await uploadLeadAttachment(leadId, file);
    setUploading(false);
    if (result.attachment) {
      setAttachments((prev) => [...prev, result.attachment!]);
    } else if (result.error) {
      setError(result.error);
      setTimeout(() => setError(null), 3000);
    }
  }

  async function handleDelete(a: LeadAttachment) {
    if (!window.confirm(`Удалить вложение «${a.filename}»?`)) return;
    const prev = attachments;
    setAttachments((list) => list.filter((x) => x.id !== a.id)); // оптимистично
    const ok = await deleteLeadAttachment(leadId, a.id);
    if (!ok) {
      setAttachments(prev); // откат: файл на месте, не вводим в заблуждение
      setError("Не удалось удалить вложение");
      setTimeout(() => setError(null), 3000);
    }
  }

  const uploadButton = (
    <div>
      <button
        type="button"
        disabled={uploading}
        onClick={() => inputRef.current?.click()}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] font-medium text-muted hover:bg-sunken disabled:opacity-60"
      >
        {uploading ? "Загрузка..." : "+ Загрузить файл"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.xlsx,.docx,.jpg,.jpeg,.png"
        onChange={handleFileChange}
        className="hidden"
      />
      {error && <div className="mt-1.5 text-[12px] text-[#DC2626]">{error}</div>}
    </div>
  );

  if (loading) {
    return <div className="text-[12.5px] text-muted">Загрузка вложений...</div>;
  }

  if (attachments.length === 0) {
    return (
      <div className="space-y-2">
        <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">Вложений нет</div>
        {uploadButton}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <ul className="space-y-1.5">
        {attachments.map((a) => {
          const badge = SOURCE_BADGE[a.source] ?? SOURCE_BADGE.manual;
          return (
            <li key={a.id} className="flex items-center gap-1.5">
              <a
                href={leadAttachmentDownloadUrl(leadId, a.id)}
                target="_blank"
                rel="noreferrer"
                className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] hover:bg-sunken"
              >
                <span aria-hidden>{iconFor(a.contentType)}</span>
                <span className="min-w-0 flex-1 truncate text-ink">{a.filename}</span>
                <span className="shrink-0 text-[11px] text-faint">{formatSize(a.sizeBytes)}</span>
                <span className={`shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${badge.cls}`}>
                  {badge.label}
                </span>
              </a>
              <button
                type="button"
                onClick={() => handleDelete(a)}
                aria-label={`Удалить вложение ${a.filename}`}
                title="Удалить"
                className="shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-[12.5px] text-muted hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950/40"
              >
                🗑
              </button>
            </li>
          );
        })}
      </ul>
      {uploadButton}
    </div>
  );
}
