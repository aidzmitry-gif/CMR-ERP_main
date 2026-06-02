import { Boxes, Plus, ShoppingCart, Truck } from "lucide-react";
import { CHATS } from "@/lib/mock-data";
import type { Chat, ChatKind } from "@/lib/types";

type IconCmp = React.ComponentType<{ size?: number }>;

const DEPT: Record<Exclude<ChatKind, "person">, { Icon: IconCmp; cls: string }> = {
  logistics: { Icon: Truck, cls: "bg-blue-100 text-blue-600" },
  purchasing: { Icon: ShoppingCart, cls: "bg-purple-100 text-purple-600" },
  warehouse: { Icon: Boxes, cls: "bg-emerald-100 text-emerald-600" },
};

function initials(name: string): string {
  return name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

function ChatAvatar({ chat }: { chat: Chat }) {
  if (chat.kind === "person") {
    return (
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-xs font-semibold text-white">
        {initials(chat.name)}
      </span>
    );
  }
  const { Icon, cls } = DEPT[chat.kind];
  return (
    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${cls}`}>
      <Icon size={16} />
    </span>
  );
}

export function ChatsPanel() {
  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5">
        <h3 className="font-semibold text-ink">Чаты и дела</h3>
        <button className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100">
          <Plus size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll">
        {CHATS.map((chat) => (
          <div key={chat.id} className="flex items-start gap-3 px-4 py-2.5 hover:bg-slate-50">
            <ChatAvatar chat={chat} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <span className="truncate text-sm font-medium text-ink">{chat.name}</span>
                <span className="ml-2 shrink-0 text-xs text-muted">{chat.time}</span>
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2">
                <p className="truncate text-xs text-muted">{chat.message}</p>
                {chat.unread ? (
                  <span className="flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500 px-1 text-[10px] font-semibold text-white">
                    {chat.unread}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-slate-200 px-4 py-3 text-right">
        <button className="text-sm font-medium text-brand-600">Все чаты и дела →</button>
      </div>
    </aside>
  );
}
