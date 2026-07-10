"use client";

import clsx from "clsx";
import {
  ArrowRight,
  Calendar,
  Check,
  ChevronRight,
  FileText,
  Flag,
  Phone,
  Plus,
  Receipt,
  ShoppingCart,
  Star,
  User,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ChannelButtons } from "@/components/channels";
import { PriorityBadge } from "@/components/priority-badge";
import { CatalogPickerModal } from "@/components/kanban/catalog-picker-modal";
import { useProductPicker } from "@/components/kanban/product-picker";
import { SourceTag } from "@/components/source-tag";
import { Button } from "@/components/ui/button";
import { fetchDocuments, issueDocument, updateDeal, type DealDoc } from "@/lib/api";
import { daysInStage, daysUntilDate, isStuck, probabilityFor, weightedAmount } from "@/lib/board";
import { presetDateISO } from "@/lib/sales-stages";
import type { Deal, Stage } from "@/lib/types";
import { formatNextStep } from "@/lib/format";
import { useCurrency } from "./currency-context";

/** Слайс 6 (A): текст авто-назначенного следующего шага после выставления счёта — единая
 *  строка для оптимистичного патча (onUpdateFields) и прямого updateDeal (fire-and-forget). */
const INVOICE_NEXT_STEP = "Проверить оплату счёта";

/** Слайс 6 (B): краткие статусы документа для компактного read-only блока «Документы»
 *  drawer'а — независимая копия deal-documents.tsx (там полноценный CRUD-список). */
const DOC_STATUS_LABEL: Record<string, string> = {
  draft: "Черновик",
  pending_approval: "На согласовании",
  posted: "Записан в 1С",
  paid: "Оплачен",
  rejected: "Отклонён",
  cancelled: "Аннулирован",
};

/**
 * Drawer-preview сделки на доске (sales-card-expanded.html прототип).
 * Цель — рабочая поверхность ИЗ канбана: продавец двигает стадию, редактирует
 * «следующий шаг», добавляет задачу, ставит ★/Win/Lose БЕЗ перехода в полную карточку.
 * 1-клик по карточке открывает drawer, 2-клика — переход на /crm/deals/[id].
 */
export function DealDrawerPreview({
  deal,
  stages,
  onClose,
  onMoveStage,
  onUpdateFields,
  onAddTask,
  onWin,
  onLose,
  onCall,
  now,
  reasonByCode,
}: {
  deal: Deal | null;
  stages: Stage[];
  onClose: () => void;
  onMoveStage: (dealId: string, stageId: string) => void;
  onUpdateFields: (dealId: string, fields: Record<string, unknown>) => void;
  onAddTask: (dealId: string, title: string) => void;
  onWin: (dealId: string) => void;
  onLose: (dealId: string) => void;
  /** Открыть окно звонка по сделке (тот же кокпит, что и у лида). */
  onCall?: (deal: Deal) => void;
  /** Текущее время (из DealsWorkspace) — для «дней в стадии»/висяка без hydration-mismatch. */
  now: number | null;
  /** code→title причины отказа (тот же резолв, что на карточке доски — SALES-40). */
  reasonByCode?: Map<string, string>;
}) {
  // Esc-закрытие
  useEffect(() => {
    if (!deal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [deal, onClose]);

  // Локальные draft-стейты для inline-редакторов (next-step + новая задача).
  // Сбрасываем, когда меняется открытая сделка, чтобы не утечь чужой текст.
  const [stepDraft, setStepDraft] = useState("");
  const [stepEditing, setStepEditing] = useState(false);
  const [taskDraft, setTaskDraft] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [docBusy, setDocBusy] = useState(false);
  const [docMsg, setDocMsg] = useState<string | null>(null);
  // Слайс 6 (B): последний счёт/договор — компактный блок «Документы».
  const [docs, setDocs] = useState<DealDoc[]>([]);
  // Справочник/остатки грузятся только пока модалка подбора реально открыта.
  const picker = useProductPicker(pickerOpen, deal?.id);
  // Сброс draft-редакторов при смене открытой сделки — «reset on key change», не каскад.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setStepDraft(deal?.nextStep ?? "");
    setStepEditing(false);
    setTaskDraft("");
    setPickerOpen(false);
    setDocMsg(null);
    setDocs([]); // не мигать документами предыдущей сделки, пока грузится свежий список
  }, [deal?.id]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Слайс 6 (B): ленивый фетч документов при открытии/смене сделки; игнорируем поздний
  // ответ, если сделку успели сменить, пока запрос летел (ignore-флаг, как useProductPicker).
  useEffect(() => {
    const dealId = deal?.id;
    if (!dealId) return;
    let ignore = false;
    void fetchDocuments(dealId).then((list) => {
      if (!ignore) setDocs(list);
    });
    return () => {
      ignore = true;
    };
  }, [deal?.id]);

  const open = deal != null;

  // Найти текущую стадию + следующую (для кнопки «→ Следующая стадия»).
  const currentStageIdx = deal
    ? stages.findIndex((s) => s.deals.some((d) => d.id === deal.id))
    : -1;
  const nextStage =
    currentStageIdx >= 0 && currentStageIdx < stages.length - 1
      ? stages[currentStageIdx + 1]
      : null;

  // Сделки 2.0 через канон board.ts (те же значения/правила, что карточка доски и список):
  // вероятность/взвешенно — probabilityFor/weightedAmount; дни/висяк — daysInStage/isStuck.
  const { fmt } = useCurrency(); // суммы в валюте выбранного ЮЛ (как карточка доски)
  const stageId = currentStageIdx >= 0 ? stages[currentStageIdx].id : "";
  const prob = deal ? probabilityFor(deal, stageId) : 0;
  const days = deal && now != null ? daysInStage(deal.stageChangedAt, now) : null;
  const stuck = deal != null && now != null && isStuck(deal, stageId, now);
  const lostTitle = deal?.lostReasonCode
    ? (reasonByCode?.get(deal.lostReasonCode) ?? deal.lostReasonCode)
    : undefined;
  const isTerminalLost = stageId === "lost" || stageId === "cond_lost";

  // Слайс 6 (B): последний счёт/договор (по max id — не полагаемся на порядок ответа бэка)
  // + человекочитаемый срок действия счёта поверх общего date-math (board.ts); своя копия
  // текста — компактный бейдж карточки (invoiceBadge, board.ts) формулирует иначе.
  const latestInvoice = [...docs].filter((d) => d.kind === "invoice").sort((a, b) => b.id - a.id)[0];
  const latestContract = [...docs].filter((d) => d.kind === "contract").sort((a, b) => b.id - a.id)[0];
  const invoiceExpiry = (() => {
    if (!latestInvoice?.valid_until || now == null) return null;
    const days = daysUntilDate(latestInvoice.valid_until, now);
    if (days < 0) return { text: `просрочен ${-days} дн`, danger: true };
    if (days === 0) return { text: "истекает сегодня", danger: true };
    return { text: `истекает через ${days} дн`, danger: days <= 2 };
  })();

  function commitStep() {
    if (!deal) return;
    const next = stepDraft.trim();
    if (next === deal.nextStep) {
      setStepEditing(false);
      return;
    }
    onUpdateFields(deal.id, { next_step: next });
    setStepEditing(false);
  }

  function addTask() {
    if (!deal || !taskDraft.trim()) return;
    onAddTask(deal.id, taskDraft.trim());
    setTaskDraft("");
  }

  /** Счёт по уже добавленным в сделку позициям (без похода в подбор товара).
   *  Слайс 6 (A): успешный счёт ВСЕГДА назначает шаг «Проверить оплату» (+3 дн) — контроль
   *  оплаты не должен повиснуть молча; неуспешный счёт/договор шаг не трогают. onUpdateFields —
   *  оптимистичный патч тем же проп-потоком, что commitStep/toggleStar ниже; updateDeal —
   *  прямой fire-and-forget (симметрично call-window.tsx: там своего onUpdateFields нет). */
  async function issueInvoice() {
    if (!deal) return;
    const dealId = deal.id;
    // Вкладку печати открываем СИНХРОННО (до await) — иначе popup-блокировщик съест окно.
    const win = window.open("about:blank", "_blank");
    setDocBusy(true);
    const { ok, message, renderUrl } = await issueDocument(dealId, "invoice");
    setDocBusy(false);
    if (win && ok && renderUrl) win.location.href = renderUrl;
    else win?.close();
    if (ok) {
      const nextStepAt = presetDateISO(3, Date.now());
      onUpdateFields(dealId, { next_step: INVOICE_NEXT_STEP, next_step_at: nextStepAt });
      void updateDeal(dealId, { next_step: INVOICE_NEXT_STEP, next_step_at: nextStepAt });
      setDocMsg(`${message} · Шаг: Проверить оплату (3 дн)`);
      void fetchDocuments(dealId).then(setDocs); // новый счёт — сразу виден в блоке «Документы»
    } else {
      setDocMsg(message);
    }
  }

  /** Договор — уходит на согласование юристу (та же ветка, что и POST /documents kind=contract). */
  async function issueContract() {
    if (!deal) return;
    const dealId = deal.id;
    setDocBusy(true);
    const { message } = await issueDocument(dealId, "contract");
    setDocBusy(false);
    setDocMsg(message);
    void fetchDocuments(dealId).then(setDocs);
  }

  function toggleStar() {
    if (!deal) return;
    onUpdateFields(deal.id, { starred: !deal.starred });
  }

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-ink/30 transition-opacity duration-150 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        role="dialog"
        aria-label={deal ? `Превью сделки ${deal.number}` : "Превью сделки"}
        aria-hidden={!open}
        className={`fixed inset-y-0 right-0 z-50 flex w-[480px] max-w-[94vw] flex-col border-l border-line bg-surface shadow-pop transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {deal && (
          <>
            {/* Шапка: номер, контрагент, описание, action-иконки (★ закрепить, ✕ закрыть) */}
            <header className="flex items-start gap-3 border-b border-line px-[18px] py-3">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] text-muted">№ {deal.number}</div>
                <h2 className="mt-px truncate text-[17px] font-extrabold text-ink">
                  {deal.company || "Контрагент не указан"}
                </h2>
                <div className="mt-0.5 truncate text-[12.5px] text-muted">
                  {deal.description || "—"}
                </div>
              </div>
              <button
                type="button"
                onClick={toggleStar}
                aria-label={deal.starred ? "Снять закрепление" : "Закрепить"}
                title={deal.starred ? "Снять закрепление" : "Закрепить"}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken"
              >
                <Star
                  size={16}
                  className={deal.starred ? "fill-amber-400 text-amber-400" : "text-faint"}
                />
              </button>
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть превью"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
              >
                <X size={16} />
              </button>
            </header>

            {/* Скроллируемое тело */}
            <div className="flex-1 overflow-y-auto px-[18px] py-[14px]">
              <div className="flex flex-wrap items-center gap-2">
                <PriorityBadge priority={deal.priority} withIcon />
                <SourceTag entity="контрагент" source="mdm/1c" />
                {days != null && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      stuck ? "bg-amber-100 text-amber-700" : "bg-sunken text-muted"
                    }`}
                  >
                    🕒 {days} дн.{stuck ? " · висяк" : ""}
                  </span>
                )}
              </div>

              {/* Причина отказа (SALES-40) — тот же резолв, что на карточке доски */}
              {lostTitle && (
                <div className="mt-2">
                  <span className="inline-block rounded-md bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">
                    Причина отказа: {lostTitle}
                  </span>
                  {deal.lostComment && (
                    <div className="mt-1 text-[12px] text-muted">{deal.lostComment}</div>
                  )}
                </div>
              )}

              {/* Сумма крупно + вероятность (канон board.ts: дефолт по стадии, как карточка/список) */}
              <div className="mt-3 text-[22px] font-extrabold tabular-nums text-ink">
                {fmt(deal.amount)}
              </div>
              {prob > 0 && (
                <div className="mt-1 text-[12px] text-muted">
                  <span className="font-semibold text-accent-ink">{prob}%</span> · взвешенно ≈{" "}
                  {fmt(weightedAmount(deal, stageId))}
                </div>
              )}

              {/* === STAGE-MOVER === */}
              <section className="mt-4">
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Стадия
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={
                      currentStageIdx >= 0 ? stages[currentStageIdx].id : ""
                    }
                    onChange={(e) => onMoveStage(deal.id, e.target.value)}
                    aria-label="Стадия сделки"
                    className="flex-1 rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink outline-none focus:border-accent"
                  >
                    {stages.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                      </option>
                    ))}
                  </select>
                  {nextStage && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => onMoveStage(deal.id, nextStage.id)}
                      icon={<ChevronRight size={14} />}
                      title={`Переместить в «${nextStage.title}»`}
                    >
                      {nextStage.title}
                    </Button>
                  )}
                </div>
              </section>

              {/* === NEXT STEP — inline edit === */}
              <section className="mt-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                    <Flag size={11} className="text-accent-ink" />
                    Следующий шаг
                  </span>
                  {!stepEditing && (
                    <button
                      type="button"
                      onClick={() => setStepEditing(true)}
                      className="text-[11px] font-semibold text-accent-ink hover:text-accent"
                    >
                      Изменить
                    </button>
                  )}
                </div>
                {stepEditing ? (
                  <div className="space-y-2">
                    <input
                      type="datetime-local"
                      autoFocus
                      value={stepDraft}
                      onChange={(e) => setStepDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitStep();
                        if (e.key === "Escape") {
                          setStepDraft(deal.nextStep ?? "");
                          setStepEditing(false);
                        }
                      }}
                      className="w-full rounded-lg border border-accent bg-surface px-2.5 py-2 text-sm text-ink outline-none"
                    />
                    <div className="flex gap-2">
                      <Button variant="primary" size="sm" onClick={commitStep} icon={<Check size={13} />}>
                        Сохранить
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setStepDraft(deal.nextStep ?? "");
                          setStepEditing(false);
                        }}
                      >
                        Отмена
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="text-[13px] text-ink">{formatNextStep(deal.nextStep)}</div>
                )}
              </section>

              {/* === QUICK TASK === */}
              <section className="mt-4">
                <div className="mb-1.5 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                  <Plus size={11} className="text-accent-ink" />
                  Быстрая задача
                </div>
                <div className="flex gap-2">
                  <input
                    value={taskDraft}
                    onChange={(e) => setTaskDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") addTask();
                    }}
                    placeholder="Позвонить, отправить КП, …"
                    className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink outline-none focus:border-accent"
                  />
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={addTask}
                    disabled={!taskDraft.trim()}
                    icon={<Plus size={13} />}
                  >
                    Добавить
                  </Button>
                </div>
              </section>

              {/* === META-список === */}
              <dl className="mt-4 divide-y divide-line border-y border-line">
                <Row label="Ответственный" icon={<User size={13} className="text-muted" />}>
                  {deal.owner || "—"}
                </Row>
                {(deal.date || deal.closedDate || deal.expectedCloseDate) && (
                  <Row
                    label={deal.closedDate ? "Закрыта" : "Ожид. закрытие"}
                    icon={<Calendar size={13} className="text-muted" />}
                  >
                    {deal.closedDate ?? deal.expectedCloseDate ?? deal.date ?? "—"}
                  </Row>
                )}
              </dl>

              {/* === ЗВОНОК → окно-кокпит (скрипт + подбор товара + позиции в сделку) === */}
              {onCall && (
                <Button
                  variant="call"
                  block
                  className="mt-4"
                  onClick={() => onCall(deal)}
                  icon={<Phone size={15} />}
                >
                  Позвонить — окно звонка
                </Button>
              )}

              {/* === ДОКУМЕНТЫ: подбор товара + счёт + договор === */}
              <section className="mt-4 grid grid-cols-3 gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPickerOpen(true)}
                  icon={<ShoppingCart size={13} />}
                >
                  Товар
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void issueInvoice()}
                  disabled={docBusy}
                  icon={<Receipt size={13} />}
                >
                  Счёт
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void issueContract()}
                  disabled={docBusy}
                  icon={<FileText size={13} />}
                >
                  Договор
                </Button>
              </section>
              {docMsg && <div className="mt-1.5 text-[11.5px] text-muted">{docMsg}</div>}

              {/* === СТАТУС ДОКУМЕНТОВ: последний счёт/договор (слайс 6, B) === */}
              {(latestInvoice || latestContract) && (
                <section className="mt-3 rounded-xl border border-line p-3">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Документы
                  </div>
                  <div className="space-y-1.5 text-[12.5px]">
                    {latestInvoice && (
                      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-ink">Счёт {latestInvoice.number}</span>
                          <span className="text-muted">· {fmt(latestInvoice.amount)}</span>
                          <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11px] font-medium text-muted">
                            {DOC_STATUS_LABEL[latestInvoice.status] ?? latestInvoice.status}
                          </span>
                          {invoiceExpiry && (
                            <span
                              className={clsx(
                                "rounded-md px-1.5 py-0.5 text-[11px] font-medium",
                                invoiceExpiry.danger
                                  ? "bg-red-50 text-red-600"
                                  : "bg-amber-50 text-amber-600",
                              )}
                            >
                              {invoiceExpiry.text}
                            </span>
                          )}
                          {latestInvoice.reserve_status === "reserved" && (
                            <span className="rounded-md bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-600">
                              резерв
                            </span>
                          )}
                        </div>
                        <a
                          href={`/api/sales/documents/${latestInvoice.id}/render`}
                          target="_blank"
                          rel="noreferrer"
                          className="shrink-0 text-[11.5px] font-semibold text-accent-ink hover:text-accent"
                        >
                          открыть
                        </a>
                      </div>
                    )}
                    {latestContract && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-ink">Договор {latestContract.number}</span>
                        <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11px] font-medium text-muted">
                          {DOC_STATUS_LABEL[latestContract.status] ?? latestContract.status}
                        </span>
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* === КАНАЛЫ СВЯЗИ (реальные кнопки звонок/WhatsApp/Telegram/Email/Viber) === */}
              <div className="mt-4 rounded-xl border border-line p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Связь с клиентом
                </div>
                <ChannelButtons dealId={deal.id} />
              </div>

              {/* === WIN / LOSE === скрываем для уже отказных (lost/cond_lost): причина показана выше */}
              {!isTerminalLost && (
                <section className="mt-4 flex flex-wrap gap-2">
                  <Button
                    variant="money"
                    size="sm"
                    onClick={() => onWin(deal.id)}
                    icon={<Check size={14} />}
                    className="flex-1"
                  >
                    Выиграна
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => onLose(deal.id)}
                    icon={<XCircle size={14} />}
                    className="flex-1"
                  >
                    Отказ
                  </Button>
                </section>
              )}

              <div className="mt-4 text-center text-[11px] text-faint">
                💡 Двойной клик по карточке открывает полную страницу
              </div>
            </div>

            <footer className="border-t border-line px-[18px] py-3">
              <Link href={`/crm/deals/${deal.id}`} className="block">
                <Button variant="secondary" block icon={<ArrowRight size={15} />}>
                  Открыть полную карточку
                </Button>
              </Link>
            </footer>
          </>
        )}
      </aside>

      {deal && pickerOpen && (
        <CatalogPickerModal
          dealId={deal.id}
          counterparty={deal.company}
          state={picker}
          onClose={() => setPickerOpen(false)}
          onCommitted={() => setPickerOpen(false)}
        />
      )}
    </>
  );
}

function Row({
  label,
  icon,
  children,
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-2 text-[13px]">
      <span className="inline-flex shrink-0 items-center gap-1.5 text-muted">
        {icon}
        {label}
      </span>
      <span className="min-w-0 text-right font-medium text-ink">{children}</span>
    </div>
  );
}
