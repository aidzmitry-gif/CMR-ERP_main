"use client";

import { X } from "lucide-react";
import { useState } from "react";
import type { LossReason } from "@/lib/types";

const SELECT = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";

/** Модалка закрытия сделки в отказ (SALES-40): причина обязательна, комментарий — опционально.
 * Без выбранной причины кнопка «Закрыть в отказ» заблокирована — нельзя слить сделку молча. */
export function LoseDealModal({
  dealLabel,
  reasons,
  onCancel,
  onConfirm,
}: {
  dealLabel: string;
  reasons: LossReason[];
  onCancel: () => void;
  onConfirm: (reasonCode: string, comment?: string) => void;
}) {
  const [reasonCode, setReasonCode] = useState("");
  const [comment, setComment] = useState("");

  function confirm() {
    if (!reasonCode) return;
    onConfirm(reasonCode, comment.trim() || undefined);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md overflow-hidden rounded-2xl bg-surface shadow-pop"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h3 className="text-base font-semibold text-ink">Закрыть сделку в отказ</h3>
          <button type="button" onClick={onCancel} className="text-faint hover:text-muted">
            <X size={20} />
          </button>
        </div>

        <div className="px-5 py-4">
          <p className="mb-3 text-xs text-muted">{dealLabel}</p>
          <label className="mb-1.5 block text-xs font-semibold text-muted">
            Причина отказа <span className="text-red-500">*</span>
          </label>
          <select
            value={reasonCode}
            onChange={(e) => setReasonCode(e.target.value)}
            className={SELECT}
            aria-label="Причина отказа"
          >
            <option value="">— выберите причину —</option>
            {reasons.map((r) => (
              <option key={r.code} value={r.code}>
                {r.title}
              </option>
            ))}
          </select>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Комментарий (необязательно)"
            className={`${SELECT} mt-3 min-h-16 resize-y`}
          />
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted hover:bg-sunken"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={!reasonCode}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Закрыть в отказ
          </button>
        </div>
      </div>
    </div>
  );
}
