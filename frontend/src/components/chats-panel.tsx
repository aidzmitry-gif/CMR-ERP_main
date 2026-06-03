"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { type ChatItem, fetchChats } from "@/lib/api";

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
  const [chats, setChats] = useState<ChatItem[]>([]);

  useEffect(() => {
    void fetchChats().then(setChats);
  }, []);

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5">
        <h3 className="font-semibold text-ink">Чаты и дела</h3>
        <Link
          href="/crm/deals"
          title="К сделкам"
          className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
        >
          <Plus size={16} />
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll">
        {chats.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted">Диалогов пока нет</p>
        )}
        {chats.map((c) => (
          <Link
            key={c.deal_id}
            href={`/crm/deals/${c.deal_id}`}
            className="flex items-start gap-3 px-4 py-2.5 hover:bg-slate-50"
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-xs font-semibold text-white">
              {initials(c.company)}
            </span>
            <div className="min-w-0 flex-1">
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
        ))}
      </div>

      <div className="border-t border-slate-200 px-4 py-3 text-right">
        <Link href="/crm/deals" className="text-sm font-medium text-brand-600">
          Все сделки →
        </Link>
      </div>
    </aside>
  );
}
