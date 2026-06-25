"use client";

import { ArrowRight, Mail, Phone, Star, User, X } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import type { Lead } from "@/lib/types";

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
}: {
  lead: Lead | null;
  busy: boolean;
  onClose: () => void;
  onQualify: (id: number) => void;
  onRoute: (id: number) => void;
  onConvert: (id: number) => void;
  onCall: (lead: Lead) => void;
}) {
  useEffect(() => {
    if (!lead) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lead, onClose]);

  const open = lead != null;
  const qualified = lead && lead.status !== "new";
  const routed = lead && (lead.status === "routed" || lead.status === "converted");
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
                onClick={() => onRoute(lead.id)}
              >
                {routed ? "✓ Распределён" : "Распределить"}
              </Button>
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
                  disabled={busy || !routed}
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
    </>
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
