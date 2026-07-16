"use client";

import clsx from "clsx";
import { useState } from "react";
import { dealStepText, type NextStepPatch } from "@/lib/board";
import {
  nextStepTemplatesFor,
  presetDateISO,
  type NextStepPreset,
} from "@/lib/sales-stages";
import type { Deal } from "@/lib/types";

// Единый источник типа — board.ts (рядом с nextStepFields, где живёт правило гашения legacy).
// Реэкспорт сохраняет существующих импортёров `@/components/kanban/next-step-composer`.
export type { NextStepPatch };

/** Пресеты срока (мокап sales-board-mockup.html): подпись + сдвиг в днях от `now`. */
const DATE_PRESETS: { label: string; days: number }[] = [
  { label: "Сегодня", days: 0 },
  { label: "Завтра", days: 1 },
  { label: "+3 дня", days: 3 },
  { label: "Неделя", days: 7 },
];

function formatPresetDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

/** Внутренности поповера — модульная функция верхнего уровня (React не даёт создавать
 * компоненты во время рендера родителя). Монтируется только когда композер открыт —
 * свежий локальный черновик (текст/срок) на каждое открытие, без риска утечки чужого draft. */
function ComposerPanel({
  deal,
  stageId,
  now,
  onSave,
  onRequestClose,
}: {
  deal: Deal;
  stageId: string | undefined;
  /** `Date.now()` — не задан вызывающим (реальное использование); тест передаёт явно.
   * Читать импульс времени в теле рендера — нечисто, поэтому фоллбэк ловим ОДИН раз
   * лениво через useState-инициализатор (свежий снимок на каждое открытие панели, т.к.
   * ComposerPanel монтируется заново при каждом открытии композера). */
  now?: number;
  onSave: (patch: NextStepPatch) => void;
  onRequestClose: () => void;
}) {
  const presets = nextStepTemplatesFor(stageId);
  const first = presets[0] as NextStepPreset | undefined;
  const currentText = dealStepText(deal);
  const hasStep = Boolean(deal.nextStep || deal.todo);
  const [autoNow] = useState(() => now ?? Date.now());
  const effectiveNow = now ?? autoNow;
  const [text, setText] = useState(first?.label ?? "");
  const [atISO, setAtISO] = useState(() => presetDateISO(first?.offsetDays ?? 0, effectiveNow));

  function pick(preset: NextStepPreset) {
    setText(preset.label);
    setAtISO(presetDateISO(preset.offsetDays, effectiveNow));
  }

  function save() {
    if (!text.trim()) return;
    onSave({ text: text.trim(), atISO });
    onRequestClose();
  }

  /** «✓ Выполнен»: очищает шаг, НО композер остаётся открытым — жест «отработал касание →
   * сразу назначаю следующее» (сбрасываем черновик на дефолтный пресет той же стадии). */
  function complete() {
    onSave({ text: null, atISO: null });
    setText(first?.label ?? "");
    setAtISO(presetDateISO(first?.offsetDays ?? 0, effectiveNow));
  }

  function completeNoNext() {
    onSave({ text: null, atISO: null });
    onRequestClose();
  }

  return (
    <div
      data-card-menu
      onPointerDown={(e) => e.stopPropagation()}
      className="absolute left-0 top-full z-20 mt-1 w-72 rounded-xl border border-line bg-surface p-3 shadow-pop"
    >
      {hasStep && (
        <div className="mb-2.5 border-b border-line pb-2.5">
          <div className="text-[11px] text-faint">Текущий шаг</div>
          <div className="text-[13px] text-ink">{currentText}</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={complete}
              className="rounded-lg bg-emerald-50 px-2.5 py-1 text-[12px] font-semibold text-emerald-700 hover:bg-emerald-100 dark:bg-emerald-500/15 dark:text-emerald-300"
            >
              ✓ Выполнен
            </button>
            <button
              type="button"
              onClick={completeNoNext}
              className="rounded-lg px-2.5 py-1 text-[12px] font-medium text-muted hover:bg-sunken"
            >
              Выполнен, без следующего
            </button>
          </div>
        </div>
      )}

      <div className="text-[11px] text-faint">Пресеты по стадии</div>
      <div className="mt-1 flex flex-col gap-0.5">
        {presets.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => pick(p)}
            className={clsx(
              "rounded-lg px-2.5 py-1.5 text-left text-[12.5px] hover:bg-sunken",
              text === p.label ? "bg-accent-soft font-semibold text-accent-ink" : "text-ink",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>

      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Свой текст шага…"
        className="mt-2 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink outline-none placeholder:text-faint focus:border-accent"
      />

      <div className="mt-2 text-[11px] text-faint">Срок: {formatPresetDate(atISO)}</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {DATE_PRESETS.map((d) => (
          <button
            key={d.label}
            type="button"
            onClick={() => setAtISO(presetDateISO(d.days, effectiveNow))}
            className={clsx(
              "rounded-md px-2 py-1 text-[11.5px] font-medium hover:bg-sunken",
              atISO === presetDateISO(d.days, effectiveNow) ? "bg-accent-soft text-accent-ink" : "text-muted",
            )}
          >
            {d.label}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={save}
        disabled={!text.trim()}
        className="mt-2.5 w-full rounded-lg bg-accent px-3 py-1.5 text-[12.5px] font-semibold text-white hover:bg-accent-ink disabled:opacity-50"
      >
        Сохранить
      </button>
    </div>
  );
}

/**
 * Строка «след. шаг» карточки + поповер назначения (слайс 4, «след. шаг в 2 клика»):
 * вся строка кликабельна (в т.ч. заглушка «+ след. шаг», когда шага нет). `open`/
 * `onOpenChange` подняты в DealCard — второй триггер (пункт CardMenu «След. шаг…»)
 * управляет тем же состоянием. Защита от drag/preview — как у CardMenu: data-card-menu
 * (DraggableDeal/StaticDealCard пропускают клик по нему) + stopPropagation.
 */
export function NextStepComposer({
  deal,
  stageId,
  open,
  onOpenChange,
  onSave,
  now,
}: {
  deal: Deal;
  stageId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (patch: NextStepPatch) => void;
  /** Тестам — фиксированный timestamp; в бою не задаётся, ComposerPanel сам поймает
   * `Date.now()` лениво через useState-инициализатор (чистый рендер, снимок на открытие). */
  now?: number;
}) {
  const stepText = dealStepText(deal);

  function stop(e: React.SyntheticEvent) {
    e.stopPropagation();
  }

  return (
    <div className="relative mt-2" data-card-menu onPointerDown={stop}>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          stop(e);
          onOpenChange(!open);
        }}
        className="block w-full rounded-md text-left text-xs text-muted hover:text-ink"
      >
        {stepText ? (
          <>
            След. шаг: <span className="text-ink">{stepText}</span>
          </>
        ) : (
          <span className="italic text-faint">+ след. шаг</span>
        )}
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-label="Закрыть композер следующего шага"
            className="fixed inset-0 z-10 cursor-default"
            onClick={(e) => {
              e.preventDefault();
              stop(e);
              onOpenChange(false);
            }}
          />
          <ComposerPanel
            deal={deal}
            stageId={stageId}
            now={now}
            onSave={onSave}
            onRequestClose={() => onOpenChange(false)}
          />
        </>
      )}
    </div>
  );
}
