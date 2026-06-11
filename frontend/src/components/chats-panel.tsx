"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { type ChatItem, fetchChats } from "@/lib/api";

/**
 * Диалог с необязательным счётчиком непрочитанных. Поле `unread` приходит из
 * бэкенда опционально — общий тип `ChatItem` намеренно НЕ расширяем здесь.
 */
type ChatWithUnread = ChatItem & { unread?: number };

function initials(name: string): string {
  return name
    .replace(/[«»"]/g, "")
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

export function ChatsPanel() {
  const [chats, setChats] = useState<ChatWithUnread[]>([]);

  useEffect(() => {
    void fetchChats().then(setChats);
  }, []);

  return (
    // Внешний слот фиксирован узким (рейка) — доска не «дышит» при наведении.
    // Видимая панель — absolute-оверлей, раскрывается влево ПОВЕРХ доски по :hover.
    <aside className="relative w-[68px] shrink-0">
      <div className="group absolute inset-y-0 right-0 z-30 flex w-[68px] flex-col overflow-hidden border-l border-slate-200 bg-white shadow-sm transition-[width] duration-300 ease-out hover:w-[300px] hover:shadow-xl">
        <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-3.5">
          <h3 className="truncate font-semibold text-ink opacity-0 transition-opacity duration-200 group-hover:opacity-100">
            Чаты и дела
          </h3>
          <Link
            href="/crm/deals"
            title="К сделкам"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
          >
            <Plus size={16} />
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto overflow-x-hidden thin-scroll">
          {chats.length === 0 && (
            <p className="px-4 py-6 text-sm text-muted opacity-0 transition-opacity duration-200 group-hover:opacity-100">
              Диалогов пока нет
            </p>
          )}
          {chats.map((c) => {
            const unread = c.unread ?? 0;
            return (
              <Link
                key={c.deal_id}
                href={`/crm/deals/${c.deal_id}`}
                className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50"
              >
                <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-xs font-semibold text-white">
                  {initials(c.company)}
                  {unread > 0 && (
                    <span
                      title={`Непрочитанных: ${unread}`}
                      className="absolute -right-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-none text-white ring-2 ring-white"
                    >
                      {unread > 99 ? "99+" : unread}
                    </span>
                  )}
                </span>
                <div className="min-w-0 flex-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                  <div className="flex items-center justify-between">
                    <span className="truncate text-sm font-medium text-ink">{c.company}</span>
                    <span className="ml-2 shrink-0 text-xs text-muted">{c.number}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted">
                    {c.direction === "in" ? "↓ " : "↑ "}
                    {c.last_text}
                  </p>
                </div>
              </Link>
            );
          })}
        </div>

        <div className="border-t border-slate-200 px-4 py-3 text-right opacity-0 transition-opacity duration-200 group-hover:opacity-100">
          <Link href="/crm/deals" className="text-sm font-medium text-brand-600">
            Все сделки →
          </Link>
        </div>
      </div>
    </aside>
  );
}
