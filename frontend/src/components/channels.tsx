import { Mail, Phone } from "lucide-react";
import { FaTelegramPlane, FaViber, FaWhatsapp } from "react-icons/fa";

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

/** Компактный ряд иконок каналов (для карточек на доске). */
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

/** Крупные круглые кнопки каналов с подписями (для карточки сделки). */
export function ChannelButtons() {
  return (
    <div className="flex items-start justify-between">
      {CHANNELS.map(({ key, label, color, Icon }) => (
        <div key={key} className="flex flex-col items-center gap-2">
          <span
            className="flex h-14 w-14 items-center justify-center rounded-full"
            style={{ backgroundColor: color + "1A", color }}
          >
            <Icon size={22} />
          </span>
          <span className="text-xs text-muted">{label}</span>
        </div>
      ))}
    </div>
  );
}
