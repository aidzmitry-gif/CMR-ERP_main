"use client";

import clsx from "clsx";
import {
  ArrowRight,
  Calendar,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  Flag,
  MessageSquare,
  Phone,
  Plus,
  Receipt,
  RefreshCw,
  ShoppingCart,
  Star,
  User,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ChannelButtons } from "@/components/channels";
import { PriorityBadge } from "@/components/priority-badge";
import { CatalogPickerModal } from "@/components/kanban/catalog-picker-modal";
import { useProductPicker } from "@/components/kanban/product-picker";
import { SourceTag } from "@/components/source-tag";
import { Button } from "@/components/ui/button";
import {
  addDealItem,
  aiDraftReply,
  createPriceQuote,
  fetchDealItems,
  fetchDocuments,
  fetchLastOrder,
  issueDocument,
  requestApproval,
  sendMessage,
  type DealDoc,
  type DealItemFull,
} from "@/lib/api";
import {
  approvalBadge,
  daysInStage,
  daysUntilDate,
  discountGate,
  isStuck,
  probabilityFor,
  weightedAmount,
} from "@/lib/board";
import {
  fetchContractTemplates,
  prepareContract,
  sendPackage,
  type ContractTemplate,
} from "@/lib/contracts-api";
import { messageTemplatesFor, presetDateISO } from "@/lib/sales-stages";
import type { Deal, Stage } from "@/lib/types";
import { formatNextStep } from "@/lib/format";
import { useCurrency } from "./currency-context";

/** Слайс 6 (A): текст авто-назначенного следующего шага после выставления счёта — единая
 *  строка для патча onUpdateFields (пропом владеет deals-workspace.tsx, шлёт и стейт, и сетевой
 *  PATCH сам — см. комментарий у issueInvoice; отдельный updateDeal здесь НЕ зовём). */
const INVOICE_NEXT_STEP = "Проверить оплату счёта";

/** Слайс 7 (B): авто-шаг после подготовки договора ПО НАШЕМУ ШАБЛОНУ — уходит на
 *  согласование сразу, контроль через 1 день (тот же паттерн, что INVOICE_NEXT_STEP). */
const CONTRACT_TEMPLATE_NEXT_STEP = "Проверить согласование договора";

/** Слайс 7 (B): авто-шаг для варианта «форма клиента» (их текст, без нашего шаблона) —
 *  юрист должен успеть вычитать риски/протокол разногласий до подписания, контроль +2 дня. */
const CONTRACT_CLIENT_NEXT_STEP = "Вычитать договор клиента: риски, протокол разногласий";

/** Слайс 8 (C): авто-шаг после отправки сообщения клиенту — сообщение слабее счёта/договора,
 *  ставится ТОЛЬКО когда у сделки ещё не было своего шага (см. sendClientMessage). */
const MESSAGE_WAIT_REPLY_STEP = "Дождаться ответа клиента";

/** Слайс 8 (D): авто-шаг после отправки пакета «счёт + договор» — сильное событие, как счёт/
 *  договор, поэтому перетирает текущий шаг ВСЕГДА (см. sendPackageToClient). */
const PACKAGE_NEXT_STEP = "Контроль получения пакета";

/** Слайс 9 (B): авто-шаг после запроса одобрения РОП на скидку — как сообщение клиенту
 *  (MESSAGE_WAIT_REPLY_STEP), НЕ перетирает уже назначенный шаг (см. requestDiscountApproval). */
const DISCOUNT_APPROVAL_NEXT_STEP = "Дождаться одобрения РОП";

/** Слайс 8 (C): каналы секции «Написать клиенту» — без телефона (звонок — отдельное окно
 *  CallWindow, см. onCall). */
const MESSAGE_CHANNELS: { key: string; label: string }[] = [
  { key: "whatsapp", label: "WhatsApp" },
  { key: "telegram", label: "Telegram" },
  { key: "email", label: "Email" },
  { key: "viber", label: "Viber" },
];

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

/** Цикл 15: факт-маржа сделки — `GET /sales/deals/{id}/margin` (тот же ответ, что читает
 *  deal-metrics.tsx; локальный тип — тот же паттерн, только поля, нужные шапке скидочного
 *  гейта ниже, api.ts не трогаем ради четырёх полей). */
type DealMargin = {
  margin_pct: number | null;
  priced_count: number;
  total_count: number;
  reason: string | null;
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
  onMessageSent,
  now,
  reasonByCode,
  approvals,
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
  /** Цикл 17: сообщение клиенту успешно ушло (композер «Написать клиенту» или пакет
   *  счёт+договор) — гасит бейдж «клиент ждёт» (deals-workspace.tsx: messages/read на бэке
   *  + локальный сброс inboundSignals). Без обработчика — поведение как раньше (не гаснет). */
  onMessageSent?: (dealId: string) => void;
  /** Текущее время (из DealsWorkspace) — для «дней в стадии»/висяка без hydration-mismatch. */
  now: number | null;
  /** code→title причины отказа (тот же резолв, что на карточке доски — SALES-40). */
  reasonByCode?: Map<string, string>;
  /** Цикл 14: dealId → status последнего согласования РОП (батч fetchApprovals({}),
   *  deals-workspace.tsx) — тот же паттерн, что reasonByCode: сырая карта, резолв здесь. */
  approvals?: Map<string, string>;
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
  // Слайс 9: позиции сделки (для мягкого скидочного гейта — прокси-маржа по min_price)
  // + СВОЙ busy для кнопки «Запросить одобрение РОП» (НЕ docBusy — гейт мягкий, счёт/договор/
  // сообщение не должны блокироваться, пока летит этот запрос).
  const [dealItems, setDealItems] = useState<DealItemFull[]>([]);
  const [gateBusy, setGateBusy] = useState(false);
  // Цикл 15: факт-маржа сделки — для шапки скидочного гейта ниже (реальная маржа рядом с
  // прокси-гейтом по min_price). Тот же ленивый фетч + dealIdRef-гард, что и dealItems ниже.
  const [margin, setMargin] = useState<DealMargin | null>(null);
  // Слайс 7: мини-секция «Договор» — выбор варианта (наш шаблон / форма клиента).
  // Шаблоны не привязаны к сделке — грузим один раз при первом открытии, кэш живёт,
  // пока смонтирован drawer (не сбрасываем при смене сделки, в отличие от docs/pickerOpen).
  const [contractOpen, setContractOpen] = useState(false);
  const [templates, setTemplates] = useState<ContractTemplate[] | null>(null);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  // Слайс 8 (C): мини-секция «Написать клиенту» — канал + свободный текст (шаблон стадии
  // подставляет text). Шаблоны синхронные (sales-stages.ts) — без своего loading-стейта.
  const [msgOpen, setMsgOpen] = useState(false);
  const [msgChannel, setMsgChannel] = useState("whatsapp");
  const [msgText, setMsgText] = useState("");
  // Справочник/остатки грузятся только пока модалка подбора реально открыта.
  const picker = useProductPicker(pickerOpen, deal?.id);
  // FIX-R6: «живой» id открытой сделки для async-колбэков документов (issueInvoice/
  // prepareContractFromTemplate/issueClientContract) — обновляется эффектом ниже, а не при
  // рендере (react-hooks/refs запрещает писать в ref во время рендера). Замыкание внутри
  // async-функции держит СТАРЫЙ dealId, поэтому сверяем именно с рефом, не с `deal?.id`.
  const dealIdRef = useRef<string | undefined>(deal?.id);
  // Сброс draft-редакторов при смене открытой сделки — «reset on key change», не каскад.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    dealIdRef.current = deal?.id;
    setStepDraft(deal?.nextStep ?? "");
    setStepEditing(false);
    setTaskDraft("");
    setPickerOpen(false);
    setDocMsg(null);
    setDocs([]); // не мигать документами предыдущей сделки, пока грузится свежий список
    setDealItems([]); // слайс 9: та же причина — не мигать позициями предыдущей сделки
    setMargin(null); // цикл 15: та же причина — не мигать маржой предыдущей сделки
    setContractOpen(false); // не действовать на чужую сделку через оставшуюся открытой секцию
    setMsgOpen(false); // слайс 8: та же причина — не писать в чужую сделку открытой секцией
    setMsgChannel("whatsapp");
    setMsgText("");
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

  // Слайс 9: ленивый фетч позиций сделки — для мягкого скидочного гейта (discountGate,
  // board.ts). Тот же dealIdRef-гард от гонки, что и в issueInvoice/prepareContractFromTemplate/
  // etc (FIX-R6) — поздний ответ по сделке, которую уже закрыли/сменили, не всыпется в стейт.
  useEffect(() => {
    const dealId = deal?.id;
    if (!dealId) return;
    void fetchDealItems(dealId).then((list) => {
      if (dealIdRef.current === dealId) setDealItems(list);
    });
  }, [deal?.id]);

  // Цикл 15: ленивый фетч факт-маржи сделки при открытии/смене — тот же dealIdRef-гард,
  // что и выше (поздний ответ по сделке, которую уже сменили, не всыпется в стейт).
  useEffect(() => {
    const dealId = deal?.id;
    if (!dealId) return;
    void fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/margin`, { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<DealMargin>) : null))
      .then((data) => {
        if (dealIdRef.current === dealId) setMargin(data);
      })
      .catch(() => {
        if (dealIdRef.current === dealId) setMargin(null);
      });
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

  // Слайс 9: мягкий скидочный гейт (прокси-маржа по min_price, board.ts) — предупреждает,
  // ничего не блокирует (см. плашку ниже и requestDiscountApproval).
  const gate = deal ? discountGate(dealItems, deal.amount) : null;

  // Цикл 14: результат последнего согласования РОП — та же карта, что резолвит бейдж
  // карточки (deals-workspace.tsx), здесь резолвим сами (как reasonByCode выше).
  const approval = deal ? approvalBadge(approvals?.get(deal.id)) : null;

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

  // Слайс 8 (D): видимость кнопки «Пакет клиенту» — ТО ЖЕ условие, что у бэка (send_package):
  // статус фильтруем ДО поиска последнего документа (latestInvoice/latestContract выше —
  // латест ВООБЩЕ, вкл. черновик/отклонённый, здесь строже — латест среди проведённых).
  const packageInvoice = [...docs]
    .filter((d) => d.kind === "invoice" && (d.status === "posted" || d.status === "paid"))
    .sort((a, b) => b.id - a.id)[0];
  const packageContract = [...docs]
    .filter((d) => d.kind === "contract" && d.status === "posted")
    .sort((a, b) => b.id - a.id)[0];
  const canSendPackage = packageInvoice != null && packageContract != null;

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
   *  ЕДИНСТВЕННЫЙ вызов, нужный для патча: пропом владеет deals-workspace.tsx, и его обработчик
   *  САМ делает и оптимистичный патч стейта, и `void updateDeal(...)` (сетевой PATCH) — see
   *  onUpdateFields в deals-workspace.tsx (~:1882). Отдельный вызов updateDeal ЗДЕСЬ был бы
   *  дублирующим сетевым PATCH (баг, пойман ревью 61fb9e9) — commitStep/toggleStar ниже всегда
   *  звали только onUpdateFields, это и есть верный паттерн. */
  async function issueInvoice() {
    if (!deal) return;
    const dealId = deal.id;
    // Вкладку печати открываем СИНХРОННО (до await) — иначе popup-блокировщик съест окно.
    const win = window.open("about:blank", "_blank");
    setDocBusy(true);
    try {
      const { ok, message, renderUrl } = await issueDocument(dealId, "invoice");
      if (win && ok && renderUrl) win.location.href = renderUrl;
      else win?.close();
      if (ok) {
        const nextStepAt = presetDateISO(3, Date.now());
        onUpdateFields(dealId, { next_step: INVOICE_NEXT_STEP, next_step_at: nextStepAt });
      }
      // FIX-R6: drawer мог переключиться на другую сделку, пока запрос летел — docs/docMsg
      // не тегированы dealId, поэтому чужой поздний ответ не должен их перезаписывать.
      if (dealIdRef.current !== dealId) return;
      if (ok) {
        setDocMsg(`${message} · Шаг: Проверить оплату (3 дн)`);
        // новый счёт — сразу виден в блоке «Документы» (тот же гард — на случай, если
        // сделку сменили уже ПОСЛЕ первой проверки, пока летел этот второй запрос).
        void fetchDocuments(dealId).then((list) => {
          if (dealIdRef.current === dealId) setDocs(list);
        });
      } else {
        setDocMsg(message);
      }
    } finally {
      // страховка от залипшего busy/окна-пустышки, если issue-путь когда-нибудь бросит
      setDocBusy(false);
    }
  }

  /** Слайс 7: открыть/закрыть мини-секцию «Договор» (выбор варианта). Шаблоны не зависят
   *  от сделки — фетчим один раз при первом открытии, дальше переиспользуем кэш. */
  function toggleContractMenu() {
    const next = !contractOpen;
    setContractOpen(next);
    if (next && templates === null && !templatesLoading) {
      setTemplatesLoading(true);
      void fetchContractTemplates().then((list) => {
        setTemplates(list);
        setTemplatesLoading(false);
      });
    }
  }

  /** Договор «по нашему шаблону» (SALES-53) — уходит на согласование сразу; авто-шаг
   *  «Проверить согласование» (+1 дн), тот же паттерн, что issueInvoice (только onUpdateFields —
   *  см. комментарий там). 409 (активный договор уже есть) / иная ошибка — только message,
   *  шаг не трогаем. `now` — таймстамп с МЕСТА КЛИКА (аргумент, не Date.now() внутри тела):
   *  функция вызывается из .map() с варьирующимся `code`, и react-compiler в этом случае
   *  считает Date.now() внутри тела «нечистым вычислением рендера» (react-hooks/purity) —
   *  ложное срабатывание для обычного обработчика клика, обходим передачей уже вычисленного
   *  значения. */
  async function prepareContractFromTemplate(code: string, now: number) {
    if (!deal) return;
    const dealId = deal.id;
    setDocBusy(true);
    const { ok, message } = await prepareContract(dealId, code);
    setDocBusy(false);
    setContractOpen(false);
    if (ok) {
      const nextStepAt = presetDateISO(1, now);
      onUpdateFields(dealId, { next_step: CONTRACT_TEMPLATE_NEXT_STEP, next_step_at: nextStepAt });
    }
    // FIX-R6: тот же гард от гонки со сменой сделки в drawer'е, что и в issueInvoice.
    if (dealIdRef.current !== dealId) return;
    if (ok) {
      setDocMsg(`${message} · Шаг: Проверить согласование (1 дн)`);
      void fetchDocuments(dealId).then((list) => {
        if (dealIdRef.current === dealId) setDocs(list);
      });
    } else {
      setDocMsg(message);
    }
  }

  /** Договор «форма клиента» (их текст, без нашего шаблона) — POST /documents kind=contract,
   *  тоже уходит на согласование юристу. Авто-шаг «Вычитать риски/протокол разногласий» (+2 дн). */
  async function issueClientContract() {
    if (!deal) return;
    const dealId = deal.id;
    setDocBusy(true);
    const { ok, message } = await issueDocument(dealId, "contract");
    setDocBusy(false);
    setContractOpen(false);
    if (ok) {
      const nextStepAt = presetDateISO(2, Date.now());
      onUpdateFields(dealId, { next_step: CONTRACT_CLIENT_NEXT_STEP, next_step_at: nextStepAt });
    }
    // FIX-R6: тот же гард от гонки со сменой сделки в drawer'е, что и в issueInvoice.
    if (dealIdRef.current !== dealId) return;
    if (ok) {
      setDocMsg(`${message} · Шаг: Вычитать договор клиента (2 дн)`);
      void fetchDocuments(dealId).then((list) => {
        if (dealIdRef.current === dealId) setDocs(list);
      });
    } else {
      setDocMsg(message);
    }
  }

  /** Слайс 8 (C): открыть/закрыть секцию «Написать клиенту» — шаблоны синхронные
   *  (sales-stages.ts), в отличие от toggleContractMenu поход в бэк не нужен. */
  function toggleMsgMenu() {
    setMsgOpen((v) => !v);
  }

  /** AI-черновик текста сообщения (AI-слой, Итерация 1). null — AI выключен/ошибка; честно
   *  показываем это в docMsg, а не притворяемся, что черновик пуст сам по себе. */
  async function draftAiMessage() {
    if (!deal) return;
    const dealId = deal.id;
    setDocBusy(true);
    const text = await aiDraftReply(dealId);
    setDocBusy(false);
    // FIX-R6: тот же гард от гонки со сменой сделки в drawer'е, что и в issueInvoice.
    if (dealIdRef.current !== dealId) return;
    if (text) setMsgText(text);
    else setDocMsg("AI-слой выключен — черновик недоступен");
  }

  /** Отправить сообщение клиенту по выбранному каналу. Авто-шаг «Дождаться ответа клиента»
   *  (+2 дн) — ТОЛЬКО если у сделки сейчас нет своего шага (ни nextStep, ни todo): сообщение —
   *  более слабое событие, чем счёт/договор (issueInvoice/prepareContractFromTemplate перетирают
   *  шаг всегда) — уже назначенный менеджером живой шаг не трогаем. */
  async function sendClientMessage() {
    if (!deal) return;
    const text = msgText.trim();
    if (!text) return;
    const dealId = deal.id;
    const channel = msgChannel;
    const hadNoStep = !deal.nextStep && !deal.todo;
    setDocBusy(true);
    const ok = await sendMessage(dealId, channel, text);
    setDocBusy(false);
    if (ok && hadNoStep) {
      const nextStepAt = presetDateISO(2, Date.now());
      onUpdateFields(dealId, { next_step: MESSAGE_WAIT_REPLY_STEP, next_step_at: nextStepAt });
    }
    // Цикл 17: сообщение ушло клиенту — гасим бейдж «клиент ждёт» (messages/read + локальный
    // сброс inboundSignals в deals-workspace.tsx). Не гейтим hadNoStep — гашение относится к
    // входящим от клиента, не к тому, был ли у сделки следующий шаг.
    if (ok) onMessageSent?.(dealId);
    // FIX-R6: тот же гард от гонки со сменой сделки в drawer'е, что и в issueInvoice.
    if (dealIdRef.current !== dealId) return;
    const channelLabel = MESSAGE_CHANNELS.find((c) => c.key === channel)?.label ?? channel;
    if (ok) {
      setMsgText("");
      setDocMsg(
        hadNoStep
          ? `✅ Отправлено (${channelLabel}) · Шаг: Дождаться ответа (2 дн)`
          : `✅ Отправлено (${channelLabel})`,
      );
    } else {
      setDocMsg("⚠️ Не отправилось");
    }
  }

  /** Слайс 8 (D): пакет «счёт + договор» одной отправкой — сильное событие (как выставление
   *  счёта), поэтому авто-шаг «Контроль получения пакета» (+1 дн) перетирает текущий ВСЕГДА. */
  async function sendPackageToClient() {
    if (!deal) return;
    const dealId = deal.id;
    setDocBusy(true);
    const { ok, message } = await sendPackage(dealId);
    setDocBusy(false);
    if (ok) {
      const nextStepAt = presetDateISO(1, Date.now());
      onUpdateFields(dealId, { next_step: PACKAGE_NEXT_STEP, next_step_at: nextStepAt });
      // Цикл 17: пакет тоже пишет исходящее сообщение в переписку (routes.py send_package) —
      // тот же гейт гашения, что sendClientMessage.
      onMessageSent?.(dealId);
    }
    // FIX-R6: тот же гард от гонки со сменой сделки в drawer'е, что и в issueInvoice.
    if (dealIdRef.current !== dealId) return;
    setDocMsg(ok ? `${message} · Шаг: Контроль получения пакета (1 дн)` : message);
  }

  /** Слайс 9 (B): запрос одобрения РОП на скидку — гейт МЯГКИЙ (плашка только предупреждает,
   *  ничего не блокирует), поэтому busy-флаг СВОЙ (gateBusy), не общий docBusy — счёт/договор/
   *  сообщение остаются кликабельными, пока летит этот запрос. Авто-шаг «Дождаться одобрения
   *  РОП» (+1 дн) — тот же паттерн, что sendClientMessage: ставим ТОЛЬКО если у сделки ещё нет
   *  своего шага (живой шаг менеджера не перетираем). */
  async function requestDiscountApproval() {
    if (!deal) return;
    const dealId = deal.id;
    const hadNoStep = !deal.nextStep && !deal.todo;
    setGateBusy(true);
    const ok = await requestApproval(dealId, "discount");
    setGateBusy(false);
    if (ok && hadNoStep) {
      const nextStepAt = presetDateISO(1, Date.now());
      onUpdateFields(dealId, { next_step: DISCOUNT_APPROVAL_NEXT_STEP, next_step_at: nextStepAt });
    }
    // FIX-R6: тот же гард от гонки со сменой сделки в drawer'е, что и в issueInvoice.
    if (dealIdRef.current !== dealId) return;
    setDocMsg(ok ? "✅ Отправлено на одобрение РОП" : "⚠️ Не удалось отправить");
  }

  function toggleStar() {
    if (!deal) return;
    onUpdateFields(deal.id, { starred: !deal.starred });
  }

  /** Сценарий B (цикл 14): повторить прошлый заказ контрагента — та же пара примитивов
   *  (addDealItem + createPriceQuote), которой пользуются commitToDeal (product-picker.tsx) и
   *  commitLeadItemsToDeal (api.ts) — не изобретаем новый способ добавить позиции в сделку.
   *  Не заводит СВОЙ picker/остатки (useProductPicker(pickerOpen, …) тут гейтит склад активным
   *  открытым пикером) — DealItemFull уже несёт `last_price` прошлой цены клиенту, этого
   *  достаточно для котировки. Честная деградация: прошлых заказов нет → сообщение, не падаем. */
  async function repeatOrder() {
    if (!deal) return;
    const dealId = deal.id;
    const counterparty = deal.company;
    setDocBusy(true);
    const items = await fetchLastOrder(dealId);
    // сделку сменили, пока летел запрос (FIX-R6) — СБРОСИТЬ docBusy, иначе на новой сделке
    // doc-кнопки (Счёт/Договор/Товар/Повторить, все disabled={docBusy}) залипнут навсегда
    // (находка opus-верификации арки).
    if (dealIdRef.current !== dealId) {
      setDocBusy(false);
      return;
    }
    if (!items.length) {
      setDocMsg("Прошлых заказов нет");
      setDocBusy(false);
      return;
    }
    const results = await Promise.all(items.map((it) => addDealItem(dealId, it.sku_id, it.qty)));
    await Promise.all(
      items.map((it) => (it.last_price ? createPriceQuote(it.code, counterparty, it.last_price) : Promise.resolve(true))),
    );
    setDocBusy(false);
    if (dealIdRef.current !== dealId) return;
    const ok = results.filter(Boolean).length;
    setDocMsg(`✅ Добавлено из прошлого заказа: ${ok}/${items.length}`);
    void fetchDealItems(dealId).then((list) => {
      if (dealIdRef.current === dealId) setDealItems(list);
    });
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
              {/* ══════════ ГРУППА 1 — КОНТЕКСТ (read-only) ══════════ */}
              <div className="flex flex-wrap items-center gap-2">
                <PriorityBadge priority={deal.priority} withIcon />
                <SourceTag entity="контрагент" source="mdm/1c" />
                {days != null && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      stuck
                        ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                        : "bg-sunken text-muted"
                    }`}
                  >
                    🕒 {days} дн.{stuck ? " · висяк" : ""}
                  </span>
                )}
              </div>

              {/* Причина отказа (SALES-40) — тот же резолв, что на карточке доски */}
              {lostTitle && (
                <div className="mt-2">
                  <span className="inline-block rounded-md bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700 dark:bg-red-500/15 dark:text-red-300">
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

              {/* === СТАТУС ОДОБРЕНИЯ РОП (цикл 14) — РЕЗУЛЬТАТ запроса скидки (не сам факт
                  запроса — тот виден по кнопке гейта ниже): approved — закрывай СЕЙЧАС по
                  согласованной цене; rejected — не одобрено. pending честно не шумит (см.
                  approvalBadge, board.ts). === */}
              {approval && (
                <div
                  role="status"
                  className={clsx(
                    "mt-3 rounded-xl border px-3 py-2.5 text-[12.5px] font-semibold",
                    approval.tone === "money"
                      ? "border-emerald-300/60 bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200"
                      : "border-red-300/60 bg-red-50 text-red-800 dark:bg-red-500/10 dark:text-red-200",
                  )}
                >
                  {approval.label}
                  <div className="mt-0.5 text-[11.5px] font-normal opacity-90">{approval.title}</div>
                </div>
              )}

              {/* === СКИДОЧНЫЙ ГЕЙТ (слайс 9) — мягкий: предупреждает, НЕ блокирует другие
                  кнопки (счёт/договор/сообщение остаются кликабельными). Прокси-маржа: реальная
                  маржа заблокирована методикой ценообразования — сравниваем с Σ min_price×qty. === */}
              {gate && (
                <div
                  role="status"
                  className="mt-3 rounded-xl border border-amber-300/60 bg-amber-50 px-3 py-2.5 text-[12.5px] text-amber-900 dark:bg-amber-500/10 dark:text-amber-200"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
                    <div className="font-semibold">
                      ⚠ Сумма ниже минимума по прайсу: {fmt(deal.amount)} при минимуме{" "}
                      {fmt(gate.minTotal)}
                    </div>
                    {/* Цикл 15: реальная маржа рядом с прокси-гейтом min_price — контекст для
                        решения по скидке. margin_pct==null покрывает и reason (фасад landed_cost
                        не подключён/ничего не оценено), и недоступность фетча (margin===null). */}
                    {margin?.margin_pct != null ? (
                      <span
                        className="shrink-0 font-semibold"
                        title={`оценено по ${margin.priced_count} из ${margin.total_count} позиций`}
                      >
                        маржа {margin.margin_pct}%
                      </span>
                    ) : (
                      // ФИКС (адверсарная верификация): reason (цикл 15) объявлен в DealMargin, но
                      // не показан — продавец не отличал «фасад закупок не подключён» от «нет
                      // позиций с ценой».
                      <span className="shrink-0 font-normal text-muted" title={margin?.reason ?? undefined}>
                        маржа не рассчитана
                      </span>
                    )}
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-2"
                    onClick={() => void requestDiscountApproval()}
                    disabled={gateBusy}
                  >
                    Запросить одобрение РОП
                  </Button>
                </div>
              )}

              {/* ══════════ ГРУППА 2 — ДВИЖЕНИЕ ПО ВОРОНКЕ ══════════ */}
              <div className="mt-5 border-t border-line pt-4">
                {/* === STAGE-MOVER === */}
                <section>
                  <SectionLabel>Стадия</SectionLabel>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={currentStageIdx >= 0 ? stages[currentStageIdx].id : ""}
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
                <section className="mt-3">
                  <SectionLabel
                    icon={<Flag size={11} className="text-accent-ink" />}
                    action={
                      !stepEditing && (
                        <button
                          type="button"
                          onClick={() => setStepEditing(true)}
                          className="text-[11px] font-semibold text-accent-ink hover:text-accent"
                        >
                          Изменить
                        </button>
                      )
                    }
                  >
                    Следующий шаг
                  </SectionLabel>
                  {stepEditing ? (
                    <div className="space-y-2">
                      {/* Поле правит ТЕКСТ шага (deal.nextStep — «Позвонить», «Проверить оплату»),
                          как и подписано. Раньше стоял type="datetime-local": пикер показывал
                          пусто (текст не дата), а сохранение писало голую дату в текстовое поле
                          и не двигало next_step_at (находка opus-верификации). Срок шага задаётся
                          пресетами/авто-шагами/композером карточки — не этим полем. */}
                      <input
                        type="text"
                        autoFocus
                        value={stepDraft}
                        onChange={(e) => setStepDraft(e.target.value)}
                        placeholder="Опишите следующий шаг…"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitStep();
                          if (e.key === "Escape") {
                            setStepDraft(deal.nextStep ?? "");
                            setStepEditing(false);
                          }
                        }}
                        className="w-full rounded-lg border border-accent bg-surface px-2.5 py-2 text-sm text-ink outline-none placeholder:text-faint"
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
                <section className="mt-3">
                  <SectionLabel icon={<Plus size={11} className="text-accent-ink" />}>
                    Быстрая задача
                  </SectionLabel>
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
                <dl className="mt-3 divide-y divide-line border-y border-line">
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
              </div>

              {/* ══════════ ГРУППА 3 — ДОКУМЕНТЫ (денежный поток) ══════════
                  Действия (Товар/Счёт/Договор) → раскрытие варианта договора под кнопкой →
                  результат последнего действия (docMsg) → статус последних счёта/договора + Пакет. */}
              <div className="mt-5 border-t border-line pt-4">
                <SectionLabel icon={<FileText size={11} className="text-accent-ink" />}>
                  Документы
                </SectionLabel>
                <div className="mt-1.5 grid grid-cols-3 gap-2">
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
                    onClick={toggleContractMenu}
                    disabled={docBusy}
                    aria-expanded={contractOpen}
                    icon={<FileText size={13} />}
                  >
                    Договор
                    <ChevronDown
                      size={12}
                      className={clsx("transition-transform", contractOpen && "rotate-180")}
                    />
                  </Button>
                </div>

                {/* === ПОВТОРИТЬ ПРОШЛЫЙ ЗАКАЗ (сценарий B, цикл 14) — самая дешёвая выручка:
                    позиции последнего заказа контрагента одной кнопкой, без похода в подбор
                    товара. Честная деградация — «Прошлых заказов нет» в docMsg, без падения. === */}
                <Button
                  variant="secondary"
                  size="sm"
                  block
                  className="mt-1.5"
                  onClick={() => void repeatOrder()}
                  disabled={docBusy}
                  icon={<RefreshCw size={13} />}
                >
                  Повторить заказ
                </Button>

                {/* === ВЫБОР ВАРИАНТА ДОГОВОРА (слайс 7): наш шаблон / форма клиента === */}
                {contractOpen && (
                  <section className="mt-2 space-y-2.5 rounded-xl border border-line bg-sunken/60 p-2.5">
                    <div>
                      <SectionLabel>По нашему шаблону</SectionLabel>
                      {templatesLoading && (
                        <div className="text-[12px] text-muted">Загрузка…</div>
                      )}
                      {!templatesLoading && templates && templates.length === 0 && (
                        <span className="inline-block rounded-md border border-line px-2 py-1 text-[12px] text-faint opacity-60">
                          Шаблонов нет
                        </span>
                      )}
                      {!templatesLoading && templates && templates.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {templates.map((t) => (
                            <button
                              key={t.code}
                              type="button"
                              onClick={() => void prepareContractFromTemplate(t.code, Date.now())}
                              disabled={docBusy}
                              className="rounded-md border border-line-strong bg-surface px-2 py-1 text-[12px] font-medium text-ink hover:bg-sunken disabled:opacity-50"
                            >
                              {t.name}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    <div>
                      <SectionLabel>Форма клиента (их договор)</SectionLabel>
                      <Button
                        variant="secondary"
                        size="sm"
                        block
                        onClick={() => void issueClientContract()}
                        disabled={docBusy}
                      >
                        Оформить по форме клиента
                      </Button>
                    </div>
                  </section>
                )}
                {docMsg && <div className="mt-1.5 text-[11.5px] text-muted">{docMsg}</div>}

                {/* === СТАТУС ДОКУМЕНТОВ: последний счёт/договор (слайс 6, B) === */}
                {(latestInvoice || latestContract) && (
                  <section className="mt-3 rounded-xl border border-line p-3">
                    <SectionLabel>Статус документов</SectionLabel>
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
                                    ? "bg-red-50 text-red-600 dark:bg-red-500/15 dark:text-red-300"
                                    : "bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300",
                                )}
                              >
                                {invoiceExpiry.text}
                              </span>
                            )}
                            {latestInvoice.reserve_status === "reserved" && (
                              <span className="rounded-md bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-600 dark:bg-sky-500/15 dark:text-sky-300">
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
                        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-ink">Договор {latestContract.number}</span>
                            <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11px] font-medium text-muted">
                              {DOC_STATUS_LABEL[latestContract.status] ?? latestContract.status}
                            </span>
                          </div>
                          <a
                            href={`/api/sales/documents/${latestContract.id}/render`}
                            target="_blank"
                            rel="noreferrer"
                            className="shrink-0 text-[11.5px] font-semibold text-accent-ink hover:text-accent"
                          >
                            открыть
                          </a>
                        </div>
                      )}
                    </div>
                    {/* Слайс 8 (D): честное отсутствие — кнопки нет, пока нет проведённого
                        счёта И проведённого договора (то же условие, что у бэка send_package). */}
                    {canSendPackage && (
                      <div className="mt-2 flex gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          block
                          onClick={() => void sendPackageToClient()}
                          disabled={docBusy}
                        >
                          📦 Пакет клиенту
                        </Button>
                        {/* Комбинированный лист счёт+договор для Ctrl+P → PDF (не фиксирует
                            факт отправки — только открывает печатную форму пакета). */}
                        <a
                          href={`/api/sales/deals/${deal.id}/package/render`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex shrink-0 items-center justify-center rounded-lg border border-line px-3 text-[12.5px] font-medium text-ink hover:bg-sunken"
                        >
                          Открыть пакет (PDF)
                        </a>
                      </div>
                    )}
                  </section>
                )}
              </div>

              {/* ══════════ ГРУППА 4 — ОБЩЕНИЕ ══════════
                  Звонок-кокпит (скрипт+подбор товара) → написать клиенту (шаблон/AI/текст) →
                  быстрые каналы связи (клик по иконке — прямая ссылка tel:/wa.me/…). */}
              <div className="mt-5 border-t border-line pt-4">
                <SectionLabel icon={<MessageSquare size={11} className="text-accent-ink" />}>
                  Общение
                </SectionLabel>
                <div className="mt-1.5 space-y-2">
                  {/* === ЗВОНОК → окно-кокпит (скрипт + подбор товара + позиции в сделку) === */}
                  {onCall && (
                    <Button variant="call" block onClick={() => onCall(deal)} icon={<Phone size={15} />}>
                      Позвонить — окно звонка
                    </Button>
                  )}

                  {/* === НАПИСАТЬ КЛИЕНТУ (слайс 8): канал + шаблон стадии + свободный текст + AI === */}
                  <Button
                    variant="secondary"
                    block
                    onClick={toggleMsgMenu}
                    aria-expanded={msgOpen}
                    icon={<MessageSquare size={15} />}
                  >
                    Написать клиенту
                    <ChevronDown size={13} className={clsx("transition-transform", msgOpen && "rotate-180")} />
                  </Button>

                  {msgOpen && (
                    <section
                      role="group"
                      aria-label="Написать клиенту"
                      className="space-y-2.5 rounded-xl border border-line bg-sunken/60 p-2.5"
                    >
                      <div className="flex gap-1.5">
                        {MESSAGE_CHANNELS.map((c) => (
                          <button
                            key={c.key}
                            type="button"
                            onClick={() => setMsgChannel(c.key)}
                            aria-pressed={msgChannel === c.key}
                            className={clsx(
                              "flex-1 rounded-md border px-2 py-1.5 text-[12px] font-medium",
                              msgChannel === c.key
                                ? "border-accent bg-accent/10 text-accent-ink"
                                : "border-line-strong bg-surface text-muted hover:bg-sunken",
                            )}
                          >
                            {c.label}
                          </button>
                        ))}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {messageTemplatesFor(stageId).map((t) => (
                          <button
                            key={t.label}
                            type="button"
                            onClick={() => setMsgText(t.text)}
                            className="rounded-md border border-line-strong bg-surface px-2 py-1 text-[12px] font-medium text-ink hover:bg-sunken"
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>
                      <textarea
                        value={msgText}
                        onChange={(e) => setMsgText(e.target.value)}
                        placeholder="Текст сообщения клиенту…"
                        aria-label="Текст сообщения клиенту"
                        rows={3}
                        className="w-full resize-none rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px] text-ink outline-none focus:border-accent"
                      />
                      <div className="flex gap-2">
                        <Button
                          variant="violet"
                          size="sm"
                          onClick={() => void draftAiMessage()}
                          disabled={docBusy}
                        >
                          AI-черновик
                        </Button>
                        <Button
                          variant="primary"
                          size="sm"
                          className="flex-1"
                          onClick={() => void sendClientMessage()}
                          disabled={docBusy || !msgText.trim()}
                        >
                          Отправить
                        </Button>
                      </div>
                    </section>
                  )}

                  {/* === КАНАЛЫ СВЯЗИ (реальные кнопки звонок/WhatsApp/Telegram/Email/Viber) === */}
                  <ChannelButtons dealId={deal.id} />
                </div>
              </div>

              {/* ══════════ ГРУППА 5 — ИСХОД ══════════
                  скрываем для уже отказных (lost/cond_lost): причина показана выше, в контексте. */}
              {!isTerminalLost && (
                <div className="mt-5 border-t border-line pt-4">
                  <section className="flex flex-wrap gap-2">
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
                </div>
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

/** Цикл 9: единый заголовок секции drawer'а — раньше ~8 мест дублировали
 *  `text-[11px] font-semibold uppercase tracking-wide text-faint` ad-hoc (иногда с иконкой,
 *  иногда с trailing-действием типа «Изменить»). Один компонент — консистентный разнобой убран. */
function SectionLabel({
  icon,
  action,
  children,
}: {
  icon?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-1.5 flex items-center justify-between gap-2">
      <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
        {icon}
        {children}
      </span>
      {action}
    </div>
  );
}
