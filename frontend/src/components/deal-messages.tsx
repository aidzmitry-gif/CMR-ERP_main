"use client";

import { Mail, MessageCircle, Phone, Save, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { FaTelegramPlane, FaViber, FaWhatsapp } from "react-icons/fa";
import { aiDraftReply, type DealMsg, fetchMessages, sendMessage } from "@/lib/api";

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
  return <DealMessagesBody key={dealId} dealId={dealId} />;
}

function DealMessagesBody({ dealId }: { dealId: string }) {
  const [items, setItems] = useState<DealMsg[]>([]);
  const [text, setText] = useState("");
  const [channel, setChannel] = useState("whatsapp");
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiNote, setAiNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const saving = useRef(false);
  const requestKey = useRef<string | null>(null);
  const mounted = useRef(false);
  const generation = useRef(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadMessages = useCallback(() => {
    const version = ++generation.current;
    return fetchMessages(dealId).then((rows) => {
      if (mounted.current && version === generation.current) setItems(rows);
    }).catch(() => {
      if (mounted.current && version === generation.current) setLoadError("Не удалось загрузить историю. Повторите попытку.");
    }).finally(() => {
      if (mounted.current && version === generation.current) setLoading(false);
    });
  }, [dealId]);

  async function refresh() {
    setLoading(true);
    setLoadError(null);
    await loadMessages();
  }

  useEffect(() => {
    mounted.current = true;
    void loadMessages();
    return () => { mounted.current = false; generation.current += 1; };
  }, [loadMessages]);

  async function onSend() {
    if (!text.trim() || saving.current || aiBusy) return;
    saving.current = true;
    setBusy(true);
    setError(null);
    requestKey.current ??= crypto.randomUUID();
    try {
      const saved = await sendMessage(dealId, channel, text.trim(), requestKey.current);
      if (!mounted.current) return;
      if (!saved) {
        setError("Не удалось сохранить запись. Повторите попытку.");
        return;
      }
      setText("");
      requestKey.current = null;
      await refresh();
    } catch {
      if (mounted.current) setError("Не удалось сохранить запись. Повторите попытку.");
    } finally {
      saving.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function onAiDraft() {
    setAiBusy(true);
    setAiNote(null);
    const draft = await aiDraftReply(dealId);
    if (!mounted.current) return;
    setAiBusy(false);
    if (draft) { requestKey.current = null; setText(draft); }
    else setAiNote("AI-слой выключен (feature-flag)");
  }

  return (
    <div className="mt-4 rounded-xl border border-line p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-ink">
          <MessageCircle size={18} className="text-accent-ink" /> Сообщения
          <span className="text-sm font-medium text-muted">({loading || loadError ? "—" : items.length})</span>
        </div>
        <select
          value={channel}
          disabled={busy || aiBusy}
          onChange={(e) => { requestKey.current = null; setChannel(e.target.value); }}
          className="rounded-lg border border-line bg-surface px-2 py-1 text-xs text-muted outline-none focus:border-accent"
        >
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {CHANNEL_META[c].label}
            </option>
          ))}
        </select>
      </div>

      <p className="mt-3 text-xs text-muted">Запись в историю общения. Клиенту сообщение не отправляется. Для отправки документов используйте «Email документов».</p>
      {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
      {loading && <p role="status" className="mt-2 text-sm text-muted">Загрузка истории…</p>}
      {loadError && <div role="alert" className="mt-2 text-sm text-red-600">{loadError} <button type="button" className="underline" onClick={() => void refresh()}>Повторить загрузку истории</button></div>}
      <div className="mt-3 space-y-3">
        {!loading && !loadError && items.length === 0 && <p className="text-sm text-muted">Переписки пока нет</p>}
        {!loading && !loadError && items.map((m) => {
          const meta = CHANNEL_META[m.channel] ?? CHANNEL_META.whatsapp;
          const Icon = meta.Icon;
          const out = m.direction === "out";
          return (
            <div key={m.id} className={`rounded-xl p-3 ${out ? "bg-blue-50" : "bg-sunken"}`}>
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
              <p className="mt-1.5 text-sm text-muted">{m.text}</p>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center justify-between">
        <button
          onClick={onAiDraft}
          disabled={busy || aiBusy}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-accent-ink hover:text-accent-ink disabled:opacity-60"
        >
          <Sparkles size={14} /> {aiBusy ? "Генерация…" : "AI-черновик ответа"}
        </button>
        {aiNote && <span className="text-xs text-amber-600">{aiNote}</span>}
      </div>

      <div className="mt-2 flex items-center gap-2">
        <input
          value={text}
          disabled={busy || aiBusy}
          onChange={(e) => { requestKey.current = null; setText(e.target.value); }}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSend();
          }}
          placeholder="Написать сообщение..."
          className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-faint focus:border-accent"
        />
        <button
          onClick={onSend}
          disabled={busy || aiBusy || !text.trim()}
          aria-label="Сохранить запись в историю"
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-white disabled:opacity-60"
        >
          <Save size={16} />
        </button>
      </div>
    </div>
  );
}
