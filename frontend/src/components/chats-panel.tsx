"use client";

import { MessageSquareText, Plus, X } from "lucide-react";
import Link from "next/link";
import { type MouseEvent, useEffect, useId, useRef, useState } from "react";
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

export function ChatsPanel({ compact = false }: { compact?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [open, setOpen] = useState(false);
  const [chats, setChats] = useState<ChatWithUnread[]>([]);

  useEffect(() => {
    if (compact && !open) return;
    let active = true;
    void fetchChats().then((items) => { if (active) setChats(items); });
    return () => { active = false; };
  }, [compact, open]);

  function closeOnNavigation(event: MouseEvent<HTMLAnchorElement>) {
    if (compact && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) dialog.current?.close();
  }

  const panel = (
      <div className={compact ? "flex max-h-[80dvh] flex-col bg-surface" : "group absolute inset-y-0 right-0 z-30 flex w-[68px] flex-col overflow-hidden border-l border-line bg-surface shadow-sm transition-[width] duration-300 ease-out hover:w-[300px] focus-within:w-[300px] hover:shadow-xl"}>
        <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3.5">
          <h3 id={titleId} className={`truncate font-semibold text-ink ${compact ? "" : "opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100"}`}>
            Лента
          </h3>
          {compact && <button type="button" aria-label="Закрыть чаты" onClick={() => dialog.current?.close()} className="ml-auto flex h-9 w-9 shrink-0 items-center justify-center rounded-lg hover:bg-sunken"><X size={18} /></button>}
          <Link
            onClick={closeOnNavigation}
            href="/crm/deals"
            title="К сделкам"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-sunken"
          >
            <Plus size={16} />
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto overflow-x-hidden thin-scroll">
          {chats.length === 0 && (
            <p className={`px-4 py-6 text-sm text-muted ${compact ? "" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"}`}>
              Диалогов пока нет
            </p>
          )}
          {chats.map((c) => {
            const unread = c.unread ?? 0;
            return (
              <Link
            onClick={closeOnNavigation}
                key={c.deal_id}
                href={`/crm/deals/${c.deal_id}`}
                className="flex items-center gap-3 px-4 py-2.5 hover:bg-sunken"
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
                <div className={`min-w-0 flex-1 ${compact ? "" : "opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100"}`}>
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

        {/* pointer-events-none: opacity-0 не отключает клики — невидимый футер перехватывал
            клики по тулбару доски под рейкой (находка ui-crawl). Кликабелен только по ховеру. */}
        <div className={`border-t border-line px-4 py-3 text-right ${compact ? "" : "pointer-events-none opacity-0 transition-opacity duration-200 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"}`}>
          <Link onClick={closeOnNavigation} href="/crm/deals" className="text-sm font-medium text-accent-ink">
            Все сделки →
          </Link>
        </div>
      </div>
  );
  if (!compact) return <aside className="relative hidden w-[68px] shrink-0 md:block">{panel}</aside>;
  return <>
    <button type="button" title="Чаты и сделки" aria-label="Открыть чаты" aria-haspopup="dialog" aria-expanded={open}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-sunken"
      onClick={() => { dialog.current?.showModal(); setOpen(true); }}><MessageSquareText size={19} /></button>
    <dialog ref={dialog} aria-labelledby={titleId} onClose={() => setOpen(false)}
      className="m-auto max-h-[85dvh] w-[min(360px,calc(100vw-24px))] max-w-none rounded-xl border border-line bg-surface p-0 text-ink shadow-pop backdrop:bg-black/30">
      {panel}
    </dialog>
  </>;
}
