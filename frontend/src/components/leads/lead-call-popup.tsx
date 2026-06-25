"use client";

import { ArrowRight, Phone, PhoneOff, Plus, Star, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { createDealTask, qualifyLead, routeLead } from "@/lib/api";
import type { Lead } from "@/lib/types";

/**
 * Screen-pop при звонке по лиду (sales-call-popup.html прототип).
 * Открывается с кнопки «Позвонить» в drawer'е лида или на самом канбане.
 * MVP: реальный исходящий звонок (originate) пока заглушка — кнопка показывает
 * «звоним...» (анимация), даёт инструмент работы с лидом в момент разговора.
 * Действия: задача / квалификация / распределение / закрыть. Привязка к
 * реальной АТС (zruchna originate) — в SALES-50-out (отдельный коммит).
 */
export function LeadCallPopup({
  lead,
  onClose,
  onPatch,
}: {
  lead: Lead | null;
  onClose: () => void;
  onPatch: (id: number, fields: Partial<Lead>) => void;
}) {
  const [phase, setPhase] = useState<"dialing" | "talking" | "summary">("dialing");
  const [taskDraft, setTaskDraft] = useState("");
  const [taskAdded, setTaskAdded] = useState(false);
  const [busy, setBusy] = useState(false);

  // Сброс при новом лиде; «звоним...» 1.5с затем «разговор».
  useEffect(() => {
    if (!lead) return;
    setPhase("dialing");
    setTaskDraft("");
    setTaskAdded(false);
    setBusy(false);
    const t = setTimeout(() => setPhase("talking"), 1500);
    return () => clearTimeout(t);
  }, [lead?.id]);

  useEffect(() => {
    if (!lead) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lead, onClose]);

  if (!lead) return null;

  async function addTask() {
    if (!lead || !taskDraft.trim()) return;
    setBusy(true);
    // createDealTask может работать и для лида: бэкенд ожидает entity_ref.
    // Если PATCH/POST вернёт ошибку — UI не блокируется (fire-and-forget).
    await createDealTask(`lead:${lead.id}`, { title: taskDraft.trim() });
    setTaskAdded(true);
    setBusy(false);
  }

  async function doQualify() {
    if (!lead) return;
    setBusy(true);
    const res = await qualifyLead(lead.id);
    if (res)
      onPatch(lead.id, {
        status: res.status,
        score: res.score,
        qualification: res.qualification,
        reason: res.reason,
        aiRationale: res.ai_rationale ?? undefined,
      });
    setBusy(false);
  }

  async function doRoute() {
    if (!lead) return;
    setBusy(true);
    const res = await routeLead(lead.id);
    if (res) onPatch(lead.id, { status: res.status, assignedTo: res.assigned_to, funnel: res.funnel });
    setBusy(false);
  }

  function endCall() {
    setPhase("summary");
  }

  return (
    <div
      aria-modal
      role="dialog"
      aria-label={`Звонок ${lead.name || lead.company || `ЛИД-${lead.id}`}`}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[420px] max-w-[94vw] overflow-hidden rounded-2xl bg-surface shadow-pop"
      >
        {/* Шапка — статус звонка */}
        <header
          className={`flex items-center gap-3 px-[18px] py-4 text-white ${
            phase === "summary"
              ? "bg-gradient-to-br from-slate-500 to-slate-700"
              : "bg-gradient-to-br from-emerald-500 to-emerald-700"
          }`}
        >
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/20 ${
              phase === "dialing" ? "animate-pulse" : ""
            }`}
          >
            {phase === "summary" ? <PhoneOff size={20} /> : <Phone size={20} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-bold">
              {phase === "dialing"
                ? "Соединение..."
                : phase === "talking"
                  ? "Разговор"
                  : "Итог звонка"}
            </div>
            <div className="truncate text-[12px] opacity-90">
              {lead.company || lead.name || `ЛИД-${lead.id}`}
              {lead.phone ? ` · ${lead.phone}` : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-white/80 hover:bg-white/20"
          >
            <X size={16} />
          </button>
        </header>

        {/* Тело — действия в момент разговора */}
        <div className="space-y-3 px-[18px] py-4">
          {/* Quick task */}
          <section>
            <div className="mb-1.5 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
              <Plus size={11} className="text-accent-ink" /> Задача ответственному
            </div>
            <div className="flex gap-2">
              <input
                value={taskDraft}
                onChange={(e) => setTaskDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void addTask();
                }}
                placeholder="Перезвонить в 15:00, выслать КП..."
                className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink outline-none focus:border-accent"
              />
              <Button
                variant="primary"
                size="sm"
                onClick={addTask}
                disabled={busy || !taskDraft.trim() || taskAdded}
              >
                {taskAdded ? "✓" : "＋"}
              </Button>
            </div>
            {taskAdded && (
              <div className="mt-1 text-[11px] text-money">Задача поставлена</div>
            )}
          </section>

          {/* Потребность — пометить визуально (без backend-патча; информация попадёт в задачу выше) */}
          <section>
            <div className="mb-1.5 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
              <Star size={11} className="text-amber-500" /> Потребность клиента
            </div>
            <div className="rounded-lg bg-sunken px-3 py-2 text-[12.5px] text-muted">
              {lead.product || "не указана — добавьте задачу выше с описанием потребности"}
            </div>
          </section>

          {/* Подбор товара со склада — линк на каталог */}
          <section>
            <Link href="/crm/catalog" className="block">
              <Button variant="secondary" block icon={<ArrowRight size={14} />}>
                Подобрать товар со склада
              </Button>
            </Link>
          </section>

          {/* Квалификация / распределение из звонка */}
          <section className="grid grid-cols-2 gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={doQualify}
              disabled={busy || lead.status !== "new"}
            >
              {lead.status !== "new" ? "✓ Квалифицирован" : "Квалифицировать"}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={doRoute}
              disabled={busy || !(lead.status === "qualified")}
            >
              {lead.status === "routed" || lead.status === "converted"
                ? "✓ Распределён"
                : "Распределить"}
            </Button>
          </section>
        </div>

        <footer className="flex gap-2 border-t border-line px-[18px] py-3">
          {phase !== "summary" ? (
            <Button variant="hangup" block onClick={endCall} icon={<PhoneOff size={14} />}>
              Завершить
            </Button>
          ) : (
            <Button variant="secondary" block onClick={onClose}>
              Закрыть
            </Button>
          )}
        </footer>
      </div>
    </div>
  );
}
