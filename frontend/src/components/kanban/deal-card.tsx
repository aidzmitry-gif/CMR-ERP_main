"use client";

import clsx from "clsx";
import { Calendar, ChevronRight, MoreHorizontal, Phone, Star, User } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PriorityBadge } from "@/components/priority-badge";
import { NextStepComposer, type NextStepPatch } from "@/components/kanban/next-step-composer";
import { fetchLeadManagers, issueDocument } from "@/lib/api";
import { dealStepText, isClosedStageId, type InvoiceBadgeResult, type InvoiceBadgeTone } from "@/lib/board";
import { formatMoney } from "@/lib/format";
import { presetDateISO } from "@/lib/sales-stages";
import type { Deal, Manager, Priority } from "@/lib/types";

/** Слайс 6 (A): текст авто-назначенного следующего шага после выставления счёта с карточки
 *  (то же самое, что делает drawer-preview при успешном issueDocument). */
const INVOICE_NEXT_STEP = "Проверить оплату счёта";

/** Слайс 6 (C): цвета бейджа статуса счёта (invoiceBadge, board.ts) на карточке. */
const INVOICE_BADGE_CLS: Record<InvoiceBadgeTone, string> = {
  green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  red: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  amber: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  neutral: "bg-sunken text-muted",
};

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

const PRIORITIES: Priority[] = ["Высокий", "Средний", "Низкий"];

/** Кэш списка менеджеров на модуль: меню открывается на сотнях карточек — грузим один раз. */
let managersCache: Manager[] | null = null;

/** Менеджеры с общим кэшем модуля (меню карточки, переключатель «Чья доска», FiltersMenu).
 * Пустой ответ (бэк недоступен) не кэшируется — следующий вызов попробует снова. */
export async function fetchManagersCached(): Promise<Manager[]> {
  if (managersCache) return managersCache;
  const list = await fetchLeadManagers();
  if (list.length) managersCache = list;
  return list;
}

/** Поля сделки, редактируемые из меню карточки (⋯). Имена совпадают с PATCH-полями
 * бэкенда (DealUpdate: owner/priority/starred) — вызывающий шлёт их в updateDeal как есть. */
export type DealCardPatch = { owner?: string; priority?: Priority; starred?: boolean };

/** Меню карточки (⋯): «Ответственный →» (менеджеры из fetchLeadManagers), «Приоритет →»,
 * «В избранное». Popover по образцу FiltersMenu; drag глушится onPointerDown stopPropagation,
 * а клик-превью доски — атрибутом data-card-menu (DraggableDeal/StaticDealCard его пропускают). */
function CardMenu({
  deal,
  onUpdate,
  onOpenNextStep,
  canIssueInvoice,
  onNextStep,
}: {
  deal: Deal;
  onUpdate: (fields: DealCardPatch) => void;
  /** Пункт «След. шаг…» — второй триггер композера (слайс 4); без него пункт не рендерится. */
  onOpenNextStep?: () => void;
  /** Слайс 6 (D): пункт «Выставить счёт» — только для открытых нетерминальных стадий. */
  canIssueInvoice: boolean;
  /** Авто-шаг «Проверить оплату» после успешного счёта (как в drawer-preview, слайс 6 A). */
  onNextStep?: (patch: NextStepPatch) => void;
}) {
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<"owner" | "priority" | null>(null);
  const [managers, setManagers] = useState<Manager[] | null>(managersCache);

  function stop(e: React.SyntheticEvent) {
    e.stopPropagation();
  }

  function close() {
    setOpen(false);
    setSection(null);
  }

  function act(fields: DealCardPatch) {
    onUpdate(fields);
    close();
  }

  function toggleOwners() {
    setSection((s) => (s === "owner" ? null : "owner"));
    if (managersCache) {
      // FIX-1: карточка могла смонтироваться ДО заполнения кэша (useState(null) на mount) —
      // синхронизируем стейт из кэша, иначе её меню навсегда застревает в «Загрузка…».
      setManagers(managersCache);
      return;
    }
    void fetchManagersCached().then(setManagers);
  }

  /** Слайс 6 (D): «Выставить счёт» прямо из меню карточки — та же цепочка, что в
   *  drawer-preview (issueDocument → авто-шаг «Проверить оплату» ВСЕГДА при успехе). Здесь
   *  нет toast-инфраструктуры карточки — alert() достаточен для редкого клика из меню. */
  async function issueInvoiceFromMenu() {
    close();
    const { ok, message, renderUrl } = await issueDocument(deal.id, "invoice");
    window.alert(message);
    if (ok) {
      onNextStep?.({ text: INVOICE_NEXT_STEP, atISO: presetDateISO(3, Date.now()) });
      if (renderUrl) window.open(renderUrl, "_blank");
    }
  }

  const itemCls =
    "flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-[13px] text-muted hover:bg-sunken";
  const subItemCls = (active: boolean) =>
    clsx(
      "block w-full rounded-lg px-2.5 py-1.5 text-left text-[13px] hover:bg-sunken",
      active ? "font-semibold text-accent-ink" : "text-muted",
    );

  return (
    <div className="relative" data-card-menu onPointerDown={stop}>
      <button
        type="button"
        aria-label="Меню карточки"
        title="Меню карточки"
        onClick={(e) => {
          e.preventDefault();
          stop(e);
          setOpen((v) => !v);
        }}
        className="flex h-5 w-5 items-center justify-center rounded-md text-faint hover:bg-sunken hover:text-muted"
      >
        <MoreHorizontal size={15} />
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-label="Закрыть меню"
            className="fixed inset-0 z-10 cursor-default"
            onClick={(e) => {
              e.preventDefault();
              stop(e);
              close();
            }}
          />
          <div className="absolute right-0 z-20 mt-1 w-52 rounded-xl border border-line bg-surface p-1 shadow-pop">
            <button type="button" onClick={toggleOwners} className={itemCls}>
              Ответственный
              <ChevronRight
                size={13}
                className={clsx("transition-transform", section === "owner" && "rotate-90")}
              />
            </button>
            {section === "owner" && (
              <div className="max-h-44 overflow-y-auto border-b border-line pb-1 pl-2">
                {managers == null ? (
                  <div className="px-2.5 py-1.5 text-xs text-faint">Загрузка…</div>
                ) : managers.length === 0 ? (
                  <div className="px-2.5 py-1.5 text-xs text-faint">Список недоступен</div>
                ) : (
                  managers.map((m) => (
                    <button
                      key={m.name}
                      type="button"
                      onClick={() => act({ owner: m.name })}
                      className={subItemCls(deal.owner === m.name)}
                    >
                      {m.name}
                      {deal.owner === m.name && " ✓"}
                    </button>
                  ))
                )}
              </div>
            )}
            <button
              type="button"
              onClick={() => setSection((s) => (s === "priority" ? null : "priority"))}
              className={itemCls}
            >
              Приоритет
              <ChevronRight
                size={13}
                className={clsx("transition-transform", section === "priority" && "rotate-90")}
              />
            </button>
            {section === "priority" && (
              <div className="border-b border-line pb-1 pl-2">
                {PRIORITIES.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => act({ priority: p })}
                    className={subItemCls(deal.priority === p)}
                  >
                    {p}
                    {deal.priority === p && " ✓"}
                  </button>
                ))}
              </div>
            )}
            <button
              type="button"
              onClick={() => act({ starred: !deal.starred })}
              className={itemCls}
            >
              <span className="inline-flex items-center gap-1.5">
                <Star size={13} className={deal.starred ? "fill-amber-400 text-amber-400" : ""} />
                {deal.starred ? "Убрать из избранного" : "В избранное"}
              </span>
            </button>
            {onOpenNextStep && (
              <button
                type="button"
                onClick={() => {
                  onOpenNextStep();
                  close();
                }}
                className={itemCls}
              >
                След. шаг…
              </button>
            )}
            {canIssueInvoice && (
              <button type="button" onClick={() => void issueInvoiceFromMenu()} className={itemCls}>
                💳 Выставить счёт
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** Карточка сделки на канбане. Бейджи/плашки Сделки 2.0 (дни в стадии SALES-43,
 * вероятность·взвешенно SALES-44, причина отказа SALES-40, срочность шага) рендерятся
 * только когда вызывающий передал соответствующий проп — иначе карточка ведёт себя как раньше.
 *
 * Кнопки «Позвонить»/«Отказ» и меню ⋯ — ВНЕ <Link>: вложенный <button> в <a> ломает клик
 * в браузерах; drag&drop на доске глушит через onPointerDown stopPropagation. */
export function DealCard({
  deal,
  days = null,
  stuck = false,
  probability,
  weighted,
  lostReasonTitle,
  wonResult = false,
  actBucket = null,
  noStep = false,
  noTouchDays = null,
  reviveDays = null,
  onLose,
  onCall,
  onUpdate,
  onNextStep,
  stageId,
  invoiceBadge,
  fmt = formatMoney,
}: {
  deal: Deal;
  days?: number | null;
  stuck?: boolean;
  probability?: number;
  weighted?: number;
  lostReasonTitle?: string;
  wonResult?: boolean;
  /** Срочность следующего шага (эталон sales-board-mockup.html, act-badge): «Просрочено» —
   * сплошной красный чип (самый горячий), «Сегодня» — красный, «Завтра» — янтарный;
   * левая кромка в тон. null — без чипа/кромки. */
  actBucket?: "overdue" | "today" | "tomorrow" | null;
  /** Открытая сделка без следующего шага — янтарный маркер «нет шага». */
  noStep?: boolean;
  /** Слайс 5 (C): сделка в стадии новой заявки БЕЗ шага — дни без первого касания.
   *  Приоритетнее общего noStep — вытесняет чип «нет шага», когда задан (не null). */
  noTouchDays?: number | null;
  /** «Условный отказ» без касания дольше порога — чип «реанимировать · N дн» (N = дни в стадии). */
  reviveDays?: number | null;
  onLose?: () => void;
  /** Открыть окно звонка прямо с карточки (без захода в drawer-preview). */
  onCall?: () => void;
  /** Меню карточки (⋯): смена ответственного/приоритета/избранного. Без обработчика
   * меню не рендерится (DragOverlay) — остаётся декоративная иконка. */
  onUpdate?: (fields: DealCardPatch) => void;
  /** Слайс 4 («след. шаг в 2 клика»): назначить/очистить следующий шаг через композер
   * (клик по строке шага или пункт CardMenu «След. шаг…»). Без обработчика строка шага
   * остаётся статичным текстом (как раньше). */
  onNextStep?: (patch: NextStepPatch) => void;
  /** Стадия сделки — пресеты композера подбираются по ней (sales-stages.ts) и решают,
   *  показывать ли пункт CardMenu «Выставить счёт» (только открытые нетерминальные). */
  stageId?: string;
  /** Слайс 6 (C): статус счёта колонки «Счёт» — уже вычисленный бейдж (invoiceBadge, board.ts),
   *  считает вызывающий (deals-workspace.tsx). Нет пропа/null — бейдж не рендерится. */
  invoiceBadge?: InvoiceBadgeResult | null;
  fmt?: (value: number) => string;
}) {
  const sideDate = deal.date ?? deal.closedDate;
  const stepText = dealStepText(deal);
  // Слайс 4: композер «след. шаг» — поднят сюда, т.к. открывается из ДВУХ мест (строка
  // шага ниже + пункт CardMenu «След. шаг…» в шапке).
  const [nextStepOpen, setNextStepOpen] = useState(false);
  const itemsLine = deal.itemsLabel
    ? [deal.itemsCount != null ? `${deal.itemsCount} поз.` : null, deal.itemsLabel]
        .filter(Boolean)
        .join(" · ")
    : null;

  function stopDrag(e: React.SyntheticEvent) {
    e.stopPropagation();
  }

  return (
    <div className="group relative rounded-xl bg-surface p-3.5 shadow-card transition-shadow hover:shadow-pop">
      {/* Цветная левая кромка у карточек с горящим шагом (эталон .card.act-today/.act-tom) —
          накладкой, чтобы не сдвигать контент и скругления. */}
      {actBucket && (
        <span
          aria-hidden
          className={clsx(
            "absolute inset-y-0 left-0 w-[3px] rounded-l-xl",
            actBucket === "tomorrow" ? "bg-amber-500" : actBucket === "today" ? "bg-red-500" : "bg-red-600",
          )}
        />
      )}
      {/* Шапка — вне <Link>: меню ⋯ это <button>, вложение в <a> ломает клики. Навигация
          по карточке на доске идёт через click-capture DraggableDeal, шапка кликабельна там же. */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted">№ {deal.number}</span>
        <div className="flex items-center gap-1.5">
          {actBucket && (
            <span
              title="Дата следующего шага"
              className={clsx(
                "inline-flex items-center rounded-[5px] px-1.5 py-0.5 text-[10px] font-bold",
                actBucket === "overdue"
                  ? "bg-red-600 text-white dark:bg-red-500"
                  : actBucket === "today"
                    ? "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300"
                    : "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
              )}
            >
              {actBucket === "overdue" ? "Просрочено" : actBucket === "today" ? "Сегодня" : "Завтра"}
            </span>
          )}
          {noTouchDays != null ? (
            // Слайс 5 (C): первое касание приоритетнее общего «нет шага» — новая заявка
            // без реакции продавца горит сильнее, чем «прогреваемая» сделка без шага.
            <span
              title="Новая заявка ещё не тронута — первое касание важнее прогрева"
              className={clsx(
                "inline-flex items-center gap-1 rounded-[5px] px-1.5 py-0.5 text-[10px] font-bold",
                noTouchDays >= 1
                  ? "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300"
                  : "bg-sunken text-muted",
              )}
            >
              ⏱ без касания {noTouchDays} дн
            </span>
          ) : (
            noStep && (
              <span
                title="У сделки нет следующего шага — назначь действие"
                className="inline-flex items-center rounded-[5px] bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
              >
                нет шага
              </span>
            )
          )}
          {reviveDays != null && (
            <span
              title="Условный отказ давно без касания — верни в работу"
              className="inline-flex items-center rounded-[5px] bg-orange-100 px-1.5 py-0.5 text-[10px] font-bold text-orange-700 dark:bg-orange-500/15 dark:text-orange-300"
            >
              реанимировать · {reviveDays} дн
            </span>
          )}
          <PriorityBadge priority={deal.priority} />
          {days != null && (
            <span
              className={clsx(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold",
                stuck ? "bg-amber-100 text-amber-700" : "bg-sunken text-muted",
              )}
            >
              🕒 {days} дн.
            </span>
          )}
          {deal.supplyArrivedAt && (
            <span
              title={`Под приход: ${deal.supplyArrivedSku ?? "товар"} · пришёл ${formatShortDate(deal.supplyArrivedAt)}`}
              className="inline-flex items-center gap-1 rounded-[5px] bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700"
            >
              🚚 {formatShortDate(deal.supplyArrivedAt)}
            </span>
          )}
          <Star
            size={14}
            className={clsx(deal.starred ? "fill-amber-400 text-amber-400" : "text-faint")}
          />
          {onUpdate ? (
            <CardMenu
              deal={deal}
              onUpdate={onUpdate}
              onOpenNextStep={onNextStep ? () => setNextStepOpen(true) : undefined}
              canIssueInvoice={!(stageId != null && isClosedStageId(stageId))}
              onNextStep={onNextStep}
            />
          ) : (
            <MoreHorizontal size={15} className="text-faint" />
          )}
        </div>
      </div>

      <Link href={`/crm/deals/${deal.id}`} className="block">
        <div className="mt-2 font-semibold text-ink">{deal.company}</div>
        <div className="text-xs text-muted">{deal.description}</div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[14.5px] font-bold text-ink">{fmt(deal.amount)}</span>
          {probability != null && probability > 0 && weighted != null && (
            <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold text-accent-ink">
              {probability}% · ≈ {fmt(weighted)}
            </span>
          )}
          {invoiceBadge && (
            <span
              className={clsx(
                "rounded-md px-1.5 py-0.5 text-[11px] font-semibold",
                INVOICE_BADGE_CLS[invoiceBadge.tone],
              )}
            >
              {invoiceBadge.label}
            </span>
          )}
        </div>

        {lostReasonTitle ? (
          <div className="mt-2">
            <span className="inline-block rounded-md bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700">
              Причина: {lostReasonTitle}
            </span>
          </div>
        ) : wonResult ? (
          <div className="mt-2">
            <span className="inline-block rounded-md bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">
              ✓ Сделка выиграна
            </span>
          </div>
        ) : null}
        {itemsLine && <div className="mt-1 text-xs text-muted">{itemsLine}</div>}
      </Link>

      {/* Слайс 4: строка «след. шаг» — ВНЕ <Link>, как кнопки «Позвонить»/«Отказ» ниже
          (вложенный <button> в <a> ломает клик): композер открывается кликом по всей строке. */}
      {!deal.todo && deal.closedDate ? (
        <div className="mt-2 text-xs text-muted">
          Дата закрытия: <span className="text-ink">{deal.closedDate}</span>
        </div>
      ) : onNextStep ? (
        <NextStepComposer
          deal={deal}
          stageId={stageId}
          open={nextStepOpen}
          onOpenChange={setNextStepOpen}
          onSave={onNextStep}
        />
      ) : (
        <div className="mt-2 text-xs text-muted">
          След. шаг: <span className="text-ink">{stepText || "—"}</span>
        </div>
      )}

      <div className="mt-2 flex items-center justify-between text-xs text-muted">
        <span className="inline-flex items-center gap-1">
          <User size={13} /> {deal.owner}
        </span>
        <div className="flex items-center gap-2">
          {sideDate && (
            <span className="inline-flex items-center gap-1">
              <Calendar size={12} /> {sideDate}
            </span>
          )}
          {onCall && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                stopDrag(e);
                onCall();
              }}
              onPointerDown={stopDrag}
              title="Позвонить — окно звонка"
              aria-label="Позвонить"
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold text-money hover:bg-money-soft"
            >
              <Phone size={13} />
            </button>
          )}
          {onLose && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                stopDrag(e);
                onLose();
              }}
              onPointerDown={stopDrag}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold text-red-700 hover:bg-red-100"
            >
              ✕ Отказ
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
