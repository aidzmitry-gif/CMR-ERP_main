"use client";

import { ArrowRight, Mail, Package, Phone, Receipt, Star, User, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CatalogPickerModal } from "@/components/kanban/catalog-picker-modal";
import { useProductPicker } from "@/components/kanban/product-picker";
import { LeadAttachments } from "@/components/leads/lead-attachments";
import { Button } from "@/components/ui/button";
import {
  commitLeadItemsToDeal,
  convertLead,
  fetchLeadItems,
  fetchLeadManagers,
  issueDocument,
  type LeadCartItem,
  saveLeadItems,
} from "@/lib/api";
import { formatByn } from "@/lib/format";
import { NEXT_STEP_PRESETS } from "@/lib/lead-next-step";
import { REJECT_REASONS } from "@/lib/types";
import type { Lead, Manager } from "@/lib/types";

const SOURCE_LABELS: Record<string, string> = {
  site: "Сайт",
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  email: "E-mail",
  phone: "Телефон",
  tender: "Тендер",
};

/**
 * Drawer-preview лида (аналог DealDrawerPreview для сделок).
 * Цель — работать ИЗ канбана: квалифицировать, распределить, конвертировать в сделку,
 * позвонить — без проваливания в полную карточку. 1-клик по лиду → drawer,
 * 2-клика → /crm/leads/[id]. Тексты кнопок — полные («Квалифицировать»/
 * «Распределить»/«В сделку»), чтобы оставаться доступными для существующих
 * тестов LeadsWorkspace и для разборчивости в reading-order.
 */
export function LeadDrawerPreview({
  lead,
  busy,
  onClose,
  onQualify,
  onRoute,
  onConvert,
  onCall,
  onReject,
  onItemsSaved,
  onConverted,
}: {
  lead: Lead | null;
  busy: boolean;
  onClose: () => void;
  onQualify: (id: number) => void;
  onRoute: (
    id: number,
    opts?: { assignedTo?: string; nextStepAt?: string; nextStepNote?: string },
  ) => void;
  onConvert: (id: number) => void;
  onCall: (lead: Lead) => void;
  onReject: (id: number, reason: string) => void;
  // Цикл 3: подбор товара сохранён на лиде → обновить бейдж КП на карточке.
  onItemsSaved?: (leadId: number, count: number, total: number) => void;
  // Цикл 3: цепочка «В сделку + счёт» сконвертировала лид → пометить его converted.
  onConverted?: (leadId: number, dealId?: number) => void;
}) {
  useEffect(() => {
    if (!lead) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lead, onClose]);

  const [managers, setManagers] = useState<Manager[]>([]);
  const [selectedManager, setSelectedManager] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [nextStepAt, setNextStepAt] = useState("");
  const [nextStepNote, setNextStepNote] = useState("");

  useEffect(() => {
    setSelectedManager(null);
    setRejectReason("");
    setNextStepAt("");
    setNextStepNote("");
    if (lead == null) {
      setManagers([]);
      return;
    }
    let cancelled = false;
    void fetchLeadManagers().then((list) => {
      if (!cancelled) setManagers(list);
    });
    return () => {
      cancelled = true;
    };
  }, [lead?.id]);

  // --- Цикл 3: подбор товара (КП) на лиде + цепочка «В сделку + счёт» ---
  const [savedItems, setSavedItems] = useState<LeadCartItem[]>([]);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [chain, setChain] = useState<ChainState | null>(null);
  // Общий стейт пикера (справочник+остатки+корзина) — как в окне звонка/сделке; грузится
  // только когда каталог открыт (active=catalogOpen), refetchKey — id лида.
  const picker = useProductPicker(catalogOpen, lead ? `lead-${lead.id}` : undefined);
  const hydratedRef = useRef(false);

  // Сохранённый подбор лида — грузим при смене лида (для списка КП и цепочки в сделку).
  useEffect(() => {
    setChain(null);
    setCatalogOpen(false);
    if (lead == null) {
      setSavedItems([]);
      return;
    }
    let cancelled = false;
    void fetchLeadItems(lead.id).then((items) => {
      if (!cancelled) setSavedItems(items);
    });
    return () => {
      cancelled = true;
    };
  }, [lead?.id]);

  // Гидрация корзины пикера из сохранённых позиций лида — один раз на открытие каталога,
  // как только загрузился справочник (skus). Пикер не отдаёт setRows наружу (файл соседней
  // полосы, править нельзя) — восстанавливаем через addSkuWithQty + setRowPrice по коду.
  useEffect(() => {
    if (!catalogOpen || hydratedRef.current || picker.skus.length === 0) return;
    hydratedRef.current = true;
    for (const it of savedItems) {
      const sku = picker.skus.find((s) => s.id === it.skuId || s.code === it.skuCode);
      if (!sku) continue;
      picker.addSkuWithQty(sku, it.qty);
      const base = picker.stock[sku.code]?.price;
      if (base != null && it.price !== base) picker.setRowPrice(sku.id, it.price);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalogOpen, picker.skus, savedItems]);

  function openPicker() {
    hydratedRef.current = false;
    setCatalogOpen(true);
  }

  // Закрытие каталога = сохранить корзину (отмеченные позиции) на лид (replace-all).
  async function closePickerAndSave() {
    if (lead == null) return setCatalogOpen(false);
    const items: LeadCartItem[] = picker.pickedRows.map((r) => {
      const base = picker.stock[r.code]?.price;
      const price = r.priceOverride ?? base ?? 0;
      const discountPct = base && base > 0 && price < base ? Math.round((1 - price / base) * 1000) / 10 : 0;
      return { skuId: r.skuId, skuCode: r.code, name: r.title, qty: r.qty, price, discountPct };
    });
    setSaving(true);
    await saveLeadItems(lead.id, items);
    setSaving(false);
    setSavedItems(items);
    setCatalogOpen(false);
    picker.reset();
    const total = items.reduce((s, it) => s + it.qty * it.price, 0);
    onItemsSaved?.(lead.id, items.length, total);
  }

  // Цепочка «В сделку + счёт»: конвертация → перенос позиций → счёт, со статусом по шагам.
  async function convertWithInvoice() {
    if (lead == null) return;
    const counterparty = lead.company || lead.name || "Новый лид";
    setChain({ deal: "run", items: "pending", invoice: "pending" });
    const conv = await convertLead(lead.id);
    if (!conv?.deal_id) {
      setChain({ deal: "err", items: "pending", invoice: "pending", error: "Сделка не создалась — сервис sales не ответил" });
      return;
    }
    const dealId = String(conv.deal_id);
    onConverted?.(lead.id, conv.deal_id);
    setChain({ deal: "ok", items: "run", invoice: "pending", dealId: conv.deal_id });

    const { ok, total } = await commitLeadItemsToDeal(dealId, counterparty, savedItems);
    if (total > 0 && ok === 0) {
      setChain({ deal: "ok", items: "err", invoice: "pending", dealId: conv.deal_id, error: "Позиции не перенеслись в сделку (сделка создана)" });
      return;
    }
    setChain({ deal: "ok", items: "ok", invoice: "run", dealId: conv.deal_id });

    const doc = await issueDocument(dealId, "invoice");
    setChain({
      deal: "ok",
      items: "ok",
      invoice: doc.ok ? "ok" : "err",
      dealId: conv.deal_id,
      renderUrl: doc.renderUrl,
      error: doc.ok ? undefined : "Счёт не выставлен (сделка и позиции готовы)",
    });
  }

  const open = lead != null;
  const qualified = lead && lead.status !== "new";
  const rejected = lead && lead.status === "rejected";
  const routed = lead && (lead.status === "routed" || lead.status === "converted" || rejected);
  const converted = lead && lead.status === "converted";

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
        aria-label={lead ? `Превью лида ЛИД-${lead.id}` : "Превью лида"}
        aria-hidden={!open}
        className={`fixed inset-y-0 right-0 z-50 flex w-[460px] max-w-[94vw] flex-col border-l border-line bg-surface shadow-pop transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {lead && (
          <>
            <header className="flex items-start gap-3 border-b border-line px-[18px] py-3">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] text-muted">
                  № ЛИД-{lead.id} · {SOURCE_LABELS[lead.source] ?? lead.source}
                </div>
                <h2 className="mt-px truncate text-[17px] font-extrabold text-ink">
                  {lead.company || lead.name || "Лид без имени"}
                </h2>
                {lead.region && (
                  <div className="mt-0.5 truncate text-[12.5px] text-muted">{lead.region}</div>
                )}
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть превью"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
              >
                <X size={16} />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-[18px] py-[14px]">
              <dl className="space-y-2 text-[13px]">
                {lead.name && lead.company && (
                  <Row icon={<User size={13} className="text-muted" />} label="Контакт">
                    {lead.name}
                  </Row>
                )}
                {lead.phone && (
                  <Row icon={<Phone size={13} className="text-muted" />} label="Телефон">
                    <span className="tabular-nums">{lead.phone}</span>
                  </Row>
                )}
                {lead.email && (
                  <Row icon={<Mail size={13} className="text-muted" />} label="E-mail">
                    {lead.email}
                  </Row>
                )}
                {lead.product && (
                  <Row icon={<Star size={13} className="text-amber-500" />} label="Интерес">
                    {lead.product}
                  </Row>
                )}
              </dl>

              {lead.message && (
                <section className="mt-4">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Сообщение
                  </div>
                  <div className="rounded-lg bg-sunken p-3 text-[13px] text-muted">
                    {lead.message}
                  </div>
                </section>
              )}

              <section className="mt-4">
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Документы
                </div>
                <LeadAttachments leadId={lead.id} />
              </section>

              <section className="mt-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Товары / КП
                  </span>
                  {!converted && !rejected && (
                    <button
                      type="button"
                      onClick={openPicker}
                      className="inline-flex items-center gap-1 text-[12px] font-semibold text-accent-ink hover:text-accent"
                    >
                      <Package size={13} /> Подобрать товары
                    </button>
                  )}
                </div>
                {savedItems.length > 0 ? (
                  <div className="rounded-lg border border-line">
                    {savedItems.map((it) => (
                      <div
                        key={it.skuId}
                        className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5 text-[12.5px] last:border-0"
                      >
                        <span className="min-w-0 flex-1 truncate text-ink">{it.name || it.skuCode}</span>
                        <span className="shrink-0 tabular-nums text-muted">
                          {it.qty} × {formatByn(it.price)}
                        </span>
                        <span className="w-24 shrink-0 text-right font-semibold tabular-nums text-ink">
                          {formatByn(it.qty * it.price)}
                        </span>
                      </div>
                    ))}
                    <div className="flex items-center justify-between px-3 py-2 text-[12.5px]">
                      <span className="font-semibold text-muted">
                        Итого · {savedItems.length} поз.
                      </span>
                      <span className="font-bold text-ink tabular-nums">
                        {formatByn(savedItems.reduce((s, it) => s + it.qty * it.price, 0))}
                      </span>
                    </div>
                  </div>
                ) : (
                  <p className="text-[12px] text-faint">
                    {converted || rejected
                      ? "Подбор не выполнялся."
                      : "Подберите товары со склада — соберётся КП, его можно перенести в сделку и счёт."}
                  </p>
                )}
              </section>

              {lead.qualification && (
                <section className="mt-4 rounded-lg border border-line p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Квалификация
                  </div>
                  <div className="mt-1 text-[13px] text-ink">
                    {lead.score} · {lead.qualification === "target" ? "целевой" : "нецелевой"}
                  </div>
                  {lead.reason && (
                    <div className="mt-1 text-[12px] text-muted">{lead.reason}</div>
                  )}
                </section>
              )}

              {rejected && (
                <section className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Отклонён
                  </div>
                  <div className="mt-1 text-[13px] text-red-700">{lead.rejectReason}</div>
                </section>
              )}

              {lead.aiRationale && (
                <section className="mt-4">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                    AI-обоснование
                  </div>
                  <div className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-[13px] text-violet-900">
                    {lead.aiRationale}
                  </div>
                </section>
              )}

              {lead.assignedTo && (
                <section className="mt-4 rounded-lg border border-line p-3 text-[13px]">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Распределение
                  </div>
                  <div className="mt-1 text-ink">
                    {lead.assignedTo}
                    {lead.funnel ? ` · ${funnelLabel(lead.funnel)}` : ""}
                  </div>
                </section>
              )}

              {qualified && !routed && !rejected && managers.length > 0 && (
                <section className="mt-4">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Кому передать
                  </div>
                  <div className="space-y-1.5">
                    {managers.map((m) => {
                      const isSelected = selectedManager === m.name;
                      return (
                        <button
                          key={m.name}
                          type="button"
                          onClick={() => setSelectedManager(isSelected ? null : m.name)}
                          className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-[13px] transition ${
                            isSelected
                              ? "border-accent bg-accent-soft text-accent-ink"
                              : "border-line text-ink hover:bg-sunken"
                          }`}
                        >
                          <span className="font-medium">{m.name}</span>
                          <span className="text-[12px] text-muted">{m.load} лидов</span>
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-1.5 text-[11px] text-faint">
                    Не выбрано — система распределит по правилам (гео/продукт/загрузка).
                  </p>

                  <div className="mt-3">
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                      Следующий шаг продавцу
                    </div>
                    <div className="mb-1.5 flex flex-wrap gap-1">
                      {NEXT_STEP_PRESETS.map((p) => (
                        <button
                          key={p.key}
                          type="button"
                          onClick={() => {
                            setNextStepAt(p.at());
                            setNextStepNote(p.note);
                          }}
                          className="rounded-full border border-line px-2 py-1 text-[11px] font-medium text-muted hover:border-accent hover:bg-accent-soft hover:text-accent-ink"
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>
                    <input
                      type="datetime-local"
                      value={nextStepAt}
                      onChange={(e) => setNextStepAt(e.target.value)}
                      className="w-full rounded-lg border border-line px-3 py-2 text-[13px]"
                    />
                    <textarea
                      placeholder="Заметка..."
                      value={nextStepNote}
                      onChange={(e) => setNextStepNote(e.target.value)}
                      rows={2}
                      className="mt-1.5 w-full rounded-lg border border-line px-3 py-2 text-[13px]"
                    />
                  </div>
                </section>
              )}

              {!routed && !rejected && (
                <section className="mt-4">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Отклонить лид
                  </div>
                  <select
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                    className="w-full rounded-lg border border-line px-3 py-2 text-[13px]"
                  >
                    {REJECT_REASONS.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onReject(lead.id, rejectReason || REJECT_REASONS[0])}
                    className="mt-1.5 w-full rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] font-medium text-red-700 hover:bg-red-100 disabled:opacity-60"
                  >
                    Отклонить
                  </button>
                </section>
              )}

              <div className="mt-4 text-center text-[11px] text-faint">
                💡 Двойной клик по лиду открывает полную карточку
              </div>
            </div>

            <footer className="space-y-2 border-t border-line px-[18px] py-3">
              {lead.phone && (
                <Button
                  variant="call"
                  block
                  onClick={() => onCall(lead)}
                  icon={<Phone size={14} />}
                >
                  Позвонить
                </Button>
              )}
              <Button
                variant="primary"
                block
                disabled={busy || !!qualified}
                onClick={() => onQualify(lead.id)}
              >
                {qualified ? "✓ Квалифицирован" : "Квалифицировать"}
              </Button>
              <Button
                variant="primary"
                block
                disabled={busy || !!routed || !qualified}
                onClick={() =>
                  onRoute(lead.id, {
                    assignedTo: selectedManager ?? undefined,
                    nextStepAt: nextStepAt || undefined,
                    nextStepNote: nextStepNote || undefined,
                  })
                }
              >
                {routed
                  ? "✓ Распределён"
                  : selectedManager
                    ? `Распределить → ${selectedManager}`
                    : "Распределить"}
              </Button>
              {routed && !converted && !rejected && savedItems.length > 0 && chain == null && (
                <Button
                  variant="money"
                  block
                  icon={<Receipt size={14} />}
                  disabled={busy}
                  onClick={convertWithInvoice}
                >
                  ⚡ В сделку + счёт
                </Button>
              )}
              {chain && (
                <div className="space-y-1 rounded-lg border border-line bg-sunken p-2.5 text-[12.5px]">
                  <StepLine label="Сделка" st={chain.deal} />
                  <StepLine label="Позиции" st={chain.items} />
                  <StepLine label="Счёт" st={chain.invoice} />
                  {chain.error && <p className="text-[11.5px] font-medium text-danger">{chain.error}</p>}
                  {chain.renderUrl && (
                    <a
                      href={chain.renderUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block text-[12px] font-semibold text-accent-ink hover:text-accent"
                    >
                      Открыть счёт →
                    </a>
                  )}
                </div>
              )}
              {converted && lead.dealId ? (
                <Link href={`/crm/deals/${lead.dealId}`} className="block">
                  <Button variant="money" block icon={<ArrowRight size={14} />}>
                    Открыть сделку
                  </Button>
                </Link>
              ) : (
                <Button
                  variant="money"
                  block
                  disabled={busy || !routed || !!rejected || chain != null}
                  onClick={() => onConvert(lead.id)}
                >
                  В сделку
                </Button>
              )}
              <Link href={`/crm/leads/${lead.id}`} className="block">
                <Button variant="secondary" block icon={<ArrowRight size={14} />}>
                  Открыть полную карточку
                </Button>
              </Link>
            </footer>
          </>
        )}
      </aside>

      {/* Каталог-пикер поверх drawer — тот же, что в сделках/звонке (без dealId: подбор
          не уходит в бэк из модалки, а собирается в общем стейте и сохраняется на лид при
          закрытии). Гидрируется из сохранённого КП лида. */}
      {catalogOpen && lead && (
        <CatalogPickerModal
          state={picker}
          counterparty={lead.company || lead.name || ""}
          onClose={closePickerAndSave}
          onCommitted={closePickerAndSave}
        />
      )}
      {saving && (
        <div className="pointer-events-none fixed bottom-4 left-1/2 z-[80] -translate-x-1/2 rounded-lg bg-ink px-4 py-2 text-[12.5px] font-semibold text-canvas shadow-pop">
          Сохраняю подбор…
        </div>
      )}
    </>
  );
}

/** Статус шага цепочки «В сделку + счёт»: pending → run → ok/err. */
type StepStatus = "pending" | "run" | "ok" | "err";
interface ChainState {
  deal: StepStatus;
  items: StepStatus;
  invoice: StepStatus;
  error?: string;
  dealId?: number;
  renderUrl?: string;
}

function StepLine({ label, st }: { label: string; st: StepStatus }) {
  const glyph = st === "ok" ? "✓" : st === "err" ? "⚠" : st === "run" ? "…" : "·";
  const cls =
    st === "ok"
      ? "text-money"
      : st === "err"
        ? "text-danger"
        : st === "run"
          ? "text-accent-ink"
          : "text-faint";
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      <span className={`font-bold ${cls}`}>{glyph}</span>
    </div>
  );
}

function funnelLabel(funnel: string): string {
  return (
    {
      new: "Новые клиенты",
      regular: "Постоянные",
      tender: "Тендеры",
      project: "Проектные",
    }[funnel] ?? funnel
  );
}

function Row({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="inline-flex shrink-0 items-center gap-1.5 text-muted">
        {icon}
        {label}
      </span>
      <span className="min-w-0 text-right font-medium text-ink">{children}</span>
    </div>
  );
}
