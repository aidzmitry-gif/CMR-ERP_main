"use client";
/* mockup — реальный API подбора в разработке */
import { X } from "lucide-react";
import { CatalogPicker } from "@/components/catalog/catalog-picker";

interface Gate1PickerModalProps {
  dealId: number;
  dealTitle: string;
  onClose: () => void;
  onConfirm: (items: unknown[]) => void;
}

export default function Gate1PickerModal({ dealTitle, onClose, onConfirm }: Gate1PickerModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="relative w-full max-w-4xl rounded-xl bg-surface shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <div>
            <span className="text-xs font-medium uppercase tracking-wider text-muted">
              Gate 1 — подбор позиций
            </span>
            <h2 className="mt-0.5 text-base font-semibold text-ink">{dealTitle}</h2>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-sunken">
            <X size={18} />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-4">
          <CatalogPicker />
        </div>
        <div className="flex items-center justify-end gap-3 border-t border-line px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm text-muted hover:bg-sunken"
          >
            Отмена
          </button>
          <button
            onClick={() => {
              onConfirm([]);
              onClose();
            }}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
          >
            Добавить в сделку
          </button>
        </div>
      </div>
    </div>
  );
}
