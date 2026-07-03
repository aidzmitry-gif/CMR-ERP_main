"use client";

import { Bell, HelpCircle, MessageSquareText } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ThemeToggle } from "@/components/theme-toggle";
import { fetchEvents, type SystemEvent } from "@/lib/api";

const EVENT_LABEL: Record<string, string> = {
  "sales.deal.created": "Создана сделка",
  "sales.document.posted": "Документ записан в 1С",
  "sales.document.created": "Сформирован документ",
  "sales.document.rejected": "Документ отклонён",
  "sales.message.sent": "Сообщение по сделке",
  "sales.stock.reserved": "Резерв остатков",
  "sales.price.quoted": "Зафиксирована цена",
  "sales.item.changed": "Изменены позиции",
  "approval.requested": "Запрос согласования",
  "approval.approved": "Согласование одобрено",
  "approval.rejected": "Согласование отклонено",
  "approval.escalated": "Эскалация согласования",
  "integration.1c.synced": "Синхронизация с 1С",
  "ai.draft.generated": "AI: черновик ответа",
  "ai.summary.generated": "AI: резюме сделки",
  "ai.next_step.generated": "AI: следующий шаг",
  "ai.insight.generated": "AI: инсайт владельцу",
  "ai.draft.suggested": "AI: предложен черновик",
};

function IconButton({
  children,
  badge,
  onClick,
  active,
  title,
}: {
  children: React.ReactNode;
  badge?: number;
  onClick?: () => void;
  active?: boolean;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`relative flex h-9 w-9 items-center justify-center rounded-lg hover:bg-sunken ${
        active ? "bg-sunken text-accent" : "text-muted"
      }`}
    >
      {children}
      {badge !== undefined && badge > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
          {badge > 9 ? "9+" : badge}
        </span>
      )}
    </button>
  );
}

export function Topbar({
  crumbs,
  headerActions,
}: {
  crumbs: string[];
  /** Доп. контент правее хлебных крошек, в одну строку (напр. переключатель ЮЛ, «Стадии»). */
  headerActions?: React.ReactNode;
}) {
  const [open, setOpen] = useState<null | "bell" | "help">(null);
  const [events, setEvents] = useState<SystemEvent[]>([]);

  useEffect(() => {
    if (open === "bell") void fetchEvents().then(setEvents);
  }, [open]);

  return (
    // flex-wrap + min-h (не фикс. h-16): при насыщенном headerActions (доска сделок:
    // ЮЛ+Фильтры+Стадии+Лого) на недостаточной ширине окна содержимое переносится на
    // вторую строку внутри шапки, а не выталкивает иконки справа за край экрана —
    // тот же класс бага, что уже чинили в строках доски (не резать, а переносить).
    <header className="relative flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-y-2 border-b border-line bg-surface px-6 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold">
          <span className="font-semibold text-muted">{crumbs[0]}</span>
          {crumbs[1] && <span className="px-1.5 text-faint">/</span>}
          {crumbs[1] && <span className="text-ink">{crumbs[1]}</span>}
        </h1>
        {headerActions}
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <IconButton
          title="Уведомления"
          badge={events.length}
          active={open === "bell"}
          onClick={() => setOpen(open === "bell" ? null : "bell")}
        >
          <Bell size={19} />
        </IconButton>
        <Link
          href="/crm/deals"
          title="Чаты и сделки"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-sunken"
        >
          <MessageSquareText size={19} />
        </Link>
        <IconButton
          title="Помощь"
          active={open === "help"}
          onClick={() => setOpen(open === "help" ? null : "help")}
        >
          <HelpCircle size={19} />
        </IconButton>
        <span className="ml-1 flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-slate-500 to-slate-700 text-xs font-semibold text-white">
          ИП
        </span>
      </div>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(null)} />
          <div className="absolute right-6 top-14 z-50 w-80 rounded-xl border border-line bg-surface p-3 shadow-pop">
            {open === "bell" && (
              <>
                <div className="mb-2 px-1 text-sm font-semibold text-ink">Уведомления</div>
                {events.length === 0 && <p className="px-1 text-sm text-muted">Событий нет</p>}
                <ul className="max-h-80 space-y-0.5 overflow-y-auto thin-scroll">
                  {events.map((e) => (
                    <li key={e.id} className="rounded-lg px-2 py-1.5 hover:bg-sunken">
                      <div className="text-sm text-ink">{EVENT_LABEL[e.event_type] ?? e.event_type}</div>
                      <div className="text-xs text-muted">
                        {e.created_at.slice(0, 16).replace("T", " ")}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {open === "help" && (
              <div className="space-y-2 px-1 text-sm text-muted">
                <div className="font-semibold text-ink">AI-First Business OS</div>
                <p>Прототип CRM/ERP. Разделы: Главная (панель владельца), CRM → Сделки (доска и карточки).</p>
                <p className="text-muted">
                  В карточке: документы с записью в 1С, согласования, AI-ассистент, каналы связи,
                  контакты и номенклатура.
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </header>
  );
}
