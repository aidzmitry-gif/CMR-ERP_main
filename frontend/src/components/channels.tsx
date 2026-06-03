"use client";

import { Mail, Phone } from "lucide-react";
import { useEffect, useState } from "react";
import { FaTelegramPlane, FaViber, FaWhatsapp } from "react-icons/fa";
import { type DealContact, fetchContacts, sendMessage } from "@/lib/api";

type IconCmp = React.ComponentType<{ size?: number }>;

interface Channel {
  key: string;
  label: string;
  color: string;
  Icon: IconCmp;
}

const CHANNELS: Channel[] = [
  { key: "phone", label: "Позвонить", color: "#22C55E", Icon: Phone },
  { key: "whatsapp", label: "WhatsApp", color: "#25D366", Icon: FaWhatsapp },
  { key: "viber", label: "Viber", color: "#7360F2", Icon: FaViber },
  { key: "telegram", label: "Telegram", color: "#229ED9", Icon: FaTelegramPlane },
  { key: "email", label: "Email", color: "#3B82F6", Icon: Mail },
];

function channelLink(channel: string, phone: string, email: string): string | null {
  const p = phone.replace(/[^\d+]/g, "");
  const digits = p.replace(/^\+/, "");
  switch (channel) {
    case "phone":
      return p ? `tel:${p}` : null;
    case "whatsapp":
      return digits ? `https://wa.me/${digits}` : null;
    case "viber":
      return p ? `viber://chat?number=${encodeURIComponent(p)}` : null;
    case "telegram":
      return digits ? `https://t.me/+${digits}` : null;
    case "email":
      return email ? `mailto:${email}` : null;
    default:
      return null;
  }
}

/** Компактный ряд иконок каналов (индикатор для карточек на доске). */
export function ChannelRow() {
  return (
    <div className="flex items-center gap-2">
      {CHANNELS.map(({ key, color, Icon }) => (
        <span
          key={key}
          className="flex h-7 w-7 items-center justify-center rounded-lg"
          style={{ backgroundColor: color + "14", color }}
        >
          <Icon size={15} />
        </span>
      ))}
    </div>
  );
}

/** Крупные кнопки каналов в карточке — открывают связь по основному контакту. */
export function ChannelButtons({ dealId }: { dealId: string }) {
  const [contact, setContact] = useState<DealContact | null>(null);

  useEffect(() => {
    void fetchContacts(dealId).then((cs) =>
      setContact(cs.find((c) => c.is_primary) ?? cs[0] ?? null),
    );
  }, [dealId]);

  function onChannel(channel: string, label: string) {
    const href = channelLink(channel, contact?.phone ?? "", contact?.email ?? "");
    if (href) window.open(href, "_blank", "noopener");
    // фиксируем контакт в истории переписки
    const who = contact ? ` — ${contact.full_name}` : "";
    void sendMessage(dealId, channel, `Связь по каналу «${label}»${who}`);
  }

  return (
    <div className="flex items-start justify-between">
      {CHANNELS.map(({ key, label, color, Icon }) => (
        <button
          key={key}
          onClick={() => onChannel(key, label)}
          title={contact?.phone || contact?.email || label}
          className="flex flex-col items-center gap-2"
        >
          <span
            className="flex h-14 w-14 items-center justify-center rounded-full transition-transform hover:scale-105"
            style={{ backgroundColor: color + "1A", color }}
          >
            <Icon size={22} />
          </span>
          <span className="text-xs text-muted">{label}</span>
        </button>
      ))}
    </div>
  );
}
