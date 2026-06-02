"use client";

import { Mail, MessageCircle, Phone, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { FaTelegramPlane, FaViber, FaWhatsapp } from "react-icons/fa";
import { type DealMsg, fetchMessages, sendMessage } from "@/lib/api";

type IconCmp = React.ComponentType<{ size?: number }>;

const CHANNEL_META: Record<string, { label: string; color: string; Icon: IconCmp }> = {
  whatsapp: { label: "WhatsApp", color: "#25D366", Icon: FaWhatsapp },
  telegram: { label: "Telegram", color: "#229ED9", Icon: FaTelegramPlane },
  email: { label: "Email", color: "#3B82F6", Icon: Mail },
  phone: { label: "Звонок", color: "#22C55E", Icon: Phone },
  viber: { label: "Viber", color: "#7360F2", Icon: FaViber },
};

const CHANNELS = ["whatsapp", "telegram", "email", "phone", "viber"];

function fmtTime(iso: string): string {
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : "";
}

export function DealMessages({ dealId }: { dealId: string }) {
  const [items, setItems] = useState<DealMsg[]>([]);
  const [text, setText] = useState("");
  const [channel, setChannel] = useState("whatsapp");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setItems(await fetchMessages(dealId));
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);

  async function onSend() {
    if (!text.trim()) return;
    setBusy(true);
    await sendMessage(dealId, channel, text.trim());
    setText("");
    await refresh();
    setBusy(false);
  }

  return (
    <div className="mt-4 rounded-xl border border-slate-200 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-ink">
          <MessageCircle size={18} className="text-brand-600" /> Сообщения
          <span className="text-sm font-medium text-muted">({items.length})</span>
        </div>
        <select
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600 outline-none focus:border-brand"
        >
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {CHANNEL_META[c].label}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-3 space-y-3">
        {items.length === 0 && <p className="text-sm text-muted">Переписки пока нет</p>}
        {items.map((m) => {
          const meta = CHANNEL_META[m.channel] ?? CHANNEL_META.whatsapp;
          const Icon = meta.Icon;
          const out = m.direction === "out";
          return (
            <div key={m.id} className={`rounded-xl p-3 ${out ? "bg-blue-50" : "bg-slate-50"}`}>
              <div className="flex items-center gap-2 text-sm">
                <span
                  className="flex h-5 w-5 items-center justify-center rounded-full"
                  style={{ backgroundColor: meta.color + "22", color: meta.color }}
                >
                  <Icon size={12} />
                </span>
                <span className="font-medium text-ink">
                  {m.author || (out ? "Менеджер" : "Клиент")}
                </span>
                <span className="text-muted">• {meta.label}</span>
                <span className="ml-auto text-xs text-muted">{fmtTime(m.created_at)}</span>
              </div>
              <p className="mt-1.5 text-sm text-slate-600">{m.text}</p>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSend();
          }}
          placeholder="Написать сообщение..."
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:border-brand"
        />
        <button
          onClick={onSend}
          disabled={busy}
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand text-white disabled:opacity-60"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
