"use client";

import { useState } from "react";

import { DealPlanEditor } from "@/components/deal-plan-editor";
import { PlanConstructor } from "@/components/plan/plan-constructor";

type ViewRole = "sales" | "rop";

/** РОП-подобные роли — стартовый вид панели (демо-тоггл ниже это переопределяет). */
function isRopRole(role: string): boolean {
  return ["rop", "РОП", "sales_head", "director", "admin"].includes(role);
}

/**
 * Единый экран планирования продавца (макет sales-plan-unified.html): сверху конструктор
 * плана из источников, снизу — панель согласования по метрикам. Без вкладок: один поток,
 * без повторного ввода. Тоггл роли (продавец/РОП) — демо-переключатель поверх серверной
 * роли: в режиме РОПа конструктор становится «только чтение» (продавец его уже собрал),
 * а панель согласования показывает кнопки решения.
 */
export function PlanningTabs({ ownerId, role }: { ownerId: number; role: string }) {
  const [view, setView] = useState<ViewRole>(() => (isRopRole(role) ? "rop" : "sales"));
  const isRop = view === "rop";

  return (
    <div className="space-y-4">
      {/* Тоггл роли */}
      <div className="flex items-center gap-3">
        <span className="text-[12.5px] text-muted">Смотрю как:</span>
        <div className="flex gap-1 rounded-xl bg-sunken p-1 text-sm font-semibold">
          <button
            type="button"
            onClick={() => setView("sales")}
            className={`rounded-lg px-3 py-1.5 transition-colors ${
              !isRop ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
            }`}
          >
            Я — продавец
          </button>
          <button
            type="button"
            onClick={() => setView("rop")}
            className={`rounded-lg px-3 py-1.5 transition-colors ${
              isRop ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
            }`}
          >
            Я — РОП
          </button>
        </div>
      </div>

      {/* Баннер режима РОПа */}
      {isRop && (
        <div className="flex items-center gap-2.5 rounded-xl bg-violet-soft px-4 py-3 text-[12.5px] font-semibold leading-relaxed text-violet-ink">
          <span className="text-[16px]">📋</span>
          <span>
            Режим РОПа · план собрал <b>продавец</b>. Ниже — как он заполнил конструктор: какие поставки,
            постоянные клиенты и расчёт активности заложены. Проверьте основание, затем согласуйте по метрикам.
          </span>
        </div>
      )}

      {/* Конструктор: в режиме РОПа — только чтение (обёртка гасит ввод, сам компонент не меняем) */}
      <div
        className={isRop ? "pointer-events-none select-none opacity-95" : undefined}
        aria-disabled={isRop || undefined}
      >
        <PlanConstructor ownerId={ownerId} />
      </div>

      {/* Стрелка потока: те же цифры уходят на согласование без повторного ввода */}
      <div className="flex items-center justify-center gap-3 py-1 text-[11.5px] font-bold text-accent-ink">
        <span className="h-px max-w-[220px] flex-1 bg-gradient-to-r from-transparent via-line-strong to-transparent" />
        <span>↓ то же собранное уходит РОПу — без повторного ввода ↓</span>
        <span className="h-px max-w-[220px] flex-1 bg-gradient-to-r from-transparent via-line-strong to-transparent" />
      </div>

      <DealPlanEditor ownerId={ownerId} role={view} />
    </div>
  );
}
