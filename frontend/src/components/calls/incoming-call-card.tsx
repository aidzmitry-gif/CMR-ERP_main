"use client";

import { MessageSquare, Phone, PhoneIncoming, PhoneOff, UserPlus, X } from "lucide-react";
import { useState } from "react";
import type { CallCard } from "@/lib/api";

// Шапка окна по статусу звонка (градиент + подпись) — как в макете sales-call-popup.
const HEAD: Record<string, { cls: string; label: string }> = {
  ringing: { cls: "from-emerald-500 to-emerald-700", label: "Входящий звонок" },
  answered: { cls: "from-accent to-accent-ink", label: "Идёт разговор" },
  ended: { cls: "from-slate-500 to-slate-700", label: "Звонок завершён" },
  missed: { cls: "from-red-500 to-red-700", label: "Пропущенный звонок" },
  busy: { cls: "from-amber-500 to-amber-700", label: "Занято" },
  failed: { cls: "from-red-500 to-red-700", label: "Звонок не состоялся" },
};

const RESULTS = ["Договорились", "Перезвонить", "Отказ", "Нет ответа", "Консультация"];

function initials(s: string): string {
  const parts = s
    .replace(/[^\dA-Za-zА-Яа-яЁё ]/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return (parts.slice(0, 2).map((p) => p[0]).join("") || "?").toUpperCase();
}

/** Всплывающее окно входящего звонка (screen-pop). Действия — реальные вызовы CRM. */
export function IncomingCallCard({
  card,
  onClose,
  onComment,
  onResult,
  onLinkDeal,
  onCreateDeal,
  onCreateLead,
  onAccept,
}: {
  card: CallCard;
  onClose: () => void;
  onComment: (text: string) => void;
  onResult: (result: string) => void;
  onLinkDeal: () => void;
  onCreateDeal: () => void;
  onCreateLead: () => void;
  /** Принять звонок → открыть рабочий кокпит разговора (CallWindow). */
  onAccept?: () => void;
}) {
  const [note, setNote] = useState("");
  const [savedNote, setSavedNote] = useState(false);

  const known = Boolean(card.owner);
  const head = HEAD[card.status] ?? HEAD.ringing;
  const phone = card.phone ?? "Неизвестный номер";
  const ended = ["ended", "missed", "busy", "failed"].includes(card.status);

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center bg-black/30 p-4 pt-20"
      onClick={onClose}
    >
      <div
        className="w-[420px] max-w-[96vw] overflow-hidden rounded-2xl bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        {/* шапка */}
        <div className={`flex items-center gap-3 bg-gradient-to-br ${head.cls} p-4 text-white`}>
          <span
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/20 ${
              card.status === "ringing" ? "animate-pulse" : ""
            }`}
          >
            {ended ? <PhoneOff size={20} /> : <PhoneIncoming size={20} />}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold">{head.label}</div>
            <div className="truncate text-xs opacity-85">
              {card.direction === "out" ? "Исходящий" : "Входящий"} · {phone}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-white/80 hover:bg-white/15"
            aria-label="Закрыть"
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-4">
          {/* клиент */}
          <div className="flex items-center gap-3">
            <span
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-sm font-bold ${
                known ? "bg-accent-soft text-accent-ink" : "bg-amber-50 text-amber-600"
              }`}
            >
              {known ? initials(card.owner) : "?"}
            </span>
            <div className="min-w-0">
              <div className="text-base font-bold text-ink">{known ? phone : "Новый номер"}</div>
              <div className="text-xs text-muted">{phone}</div>
            </div>
          </div>

          {/* владелец / резолв */}
          <div
            className={`mt-3 rounded-lg px-3 py-2 text-xs ${
              known ? "bg-sunken text-muted" : "bg-amber-50 text-amber-600"
            }`}
          >
            {known ? (
              <>
                Закреплён за: <span className="font-semibold text-ink">{card.owner}</span>
              </>
            ) : (
              "Номер не найден в CRM — создайте лид или сделку."
            )}
          </div>

          {/* сделка */}
          {card.deal_id ? (
            <button
              onClick={onLinkDeal}
              className="mt-3 flex w-full items-center justify-between rounded-xl border border-line px-3 py-2.5 text-sm hover:bg-sunken"
            >
              <span className="font-semibold text-ink">Сделка #{card.deal_id}</span>
              <span className="text-xs font-medium text-accent-ink">Провалиться →</span>
            </button>
          ) : known ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              Активных сделок нет — пора перезаказ? Оформите прямо в разговоре.
            </div>
          ) : null}

          {/* итог звонка (после завершения) */}
          {ended && (
            <div className="mt-3">
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                Итог звонка
              </div>
              <div className="flex flex-wrap gap-1.5">
                {RESULTS.map((r) => (
                  <button
                    key={r}
                    onClick={() => onResult(r)}
                    className="rounded-full border border-line px-3 py-1 text-xs font-medium text-muted hover:border-accent hover:text-accent-ink"
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* комментарий */}
          <div className="mt-3">
            <textarea
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setSavedNote(false);
              }}
              placeholder="Комментарий по звонку…"
              className="min-h-[56px] w-full resize-y rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-faint focus:border-accent"
            />
            <button
              onClick={() => {
                if (note.trim()) {
                  onComment(note.trim());
                  setSavedNote(true);
                }
              }}
              disabled={!note.trim()}
              className="mt-1.5 inline-flex items-center gap-1.5 rounded-lg bg-sunken px-3 py-1.5 text-xs font-medium text-muted hover:text-ink disabled:opacity-50"
            >
              <MessageSquare size={14} /> {savedNote ? "Сохранено ✓" : "Сохранить комментарий"}
            </button>
          </div>

          {/* приём звонка → рабочий кокпит разговора (скрипт + подбор товара + счёт) */}
          {!ended && onAccept && (
            <div className="mt-4 flex gap-2">
              <button
                onClick={onAccept}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-money px-3 py-2.5 text-sm font-semibold text-white hover:brightness-105"
              >
                <Phone size={15} /> Принять
              </button>
              <button
                onClick={() => onResult("Нет ответа")}
                className="flex items-center justify-center gap-1.5 rounded-xl border border-line px-4 py-2.5 text-sm font-semibold text-muted hover:bg-sunken"
              >
                <PhoneOff size={15} /> Отклонить
              </button>
            </div>
          )}

          {/* создать запись из звонка (вторично — или когда приём недоступен) */}
          <div className="mt-2 flex gap-2">
            <button
              onClick={onCreateDeal}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-line px-3 py-2 text-[13px] font-semibold text-muted hover:bg-sunken"
            >
              <Phone size={14} /> Создать сделку
            </button>
            {!known && (
              <button
                onClick={onCreateLead}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-line px-3 py-2 text-[13px] font-semibold text-muted hover:bg-sunken"
              >
                <UserPlus size={14} /> Создать лид
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
