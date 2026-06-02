import Link from "next/link";
import {
  ArrowLeft,
  Calendar,
  ChevronDown,
  ChevronRight,
  Filter,
  Flag,
  MessageCircle,
  Package,
  Pencil,
  Send,
  Star,
  Target,
  User,
} from "lucide-react";
import { FaWhatsapp } from "react-icons/fa";
import { ChannelButtons } from "@/components/channels";
import { PriorityBadge } from "@/components/priority-badge";
import { formatMoney } from "@/lib/format";
import { getDealDetail } from "@/lib/mock-data";

export default async function DealDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = getDealDetail(id);

  return (
    <div className="mx-auto max-w-md px-4 py-6">
      <Link
        href="/crm/deals"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"
      >
        <ArrowLeft size={16} /> К сделкам
      </Link>

      <div className="rounded-2xl bg-white p-5 shadow-card">
        {/* Шапка */}
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted">№ {d.number}</span>
          <div className="flex items-center gap-2">
            <PriorityBadge priority={d.priority} withIcon />
            <button className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-500">
              <Pencil size={15} />
            </button>
            <button className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-400">
              <Star size={15} />
            </button>
          </div>
        </div>

        <h1 className="mt-3 text-2xl font-bold text-ink">{d.company}</h1>
        <p className="text-muted">{d.description}</p>
        <div className="mt-3 text-2xl font-bold text-ink">{formatMoney(d.amount)}</div>

        {/* След. шаг */}
        <div className="mt-3 flex items-center gap-2 text-sm">
          <Flag size={16} className="text-brand-600" />
          <span className="text-muted">След. шаг:</span>
          <span className="font-medium text-ink">{d.nextStep}</span>
        </div>

        {/* Контакт + дата */}
        <div className="mt-4 flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
          <span className="inline-flex items-center gap-2 text-sm text-ink">
            <User size={16} className="text-slate-400" /> {d.contact}
          </span>
          <button className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-ink">
            <Calendar size={15} className="text-brand-600" /> {d.datetime}
            <ChevronRight size={15} className="text-slate-400" />
          </button>
        </div>

        {/* Номенклатура */}
        <div className="mt-4 rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-2 font-semibold text-ink">
            <Package size={18} className="text-brand-600" />
            {d.itemsTitle} <span className="font-medium text-brand-600">({d.items.length} поз.)</span>
          </div>
          <ul className="mt-3 space-y-2">
            {d.items.map((item) => (
              <li key={item} className="flex gap-2 text-sm text-slate-600">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />
                {item}
              </li>
            ))}
          </ul>
          <button className="mt-3 inline-flex items-center gap-1.5 text-sm text-brand-600">
            <Pencil size={14} /> Редактировать товар
          </button>
        </div>

        {/* Сообщения */}
        <div className="mt-4 rounded-xl border border-slate-200 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold text-ink">
              <MessageCircle size={18} className="text-brand-600" /> Сообщения
            </div>
            <div className="flex items-center gap-2">
              <button className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600">
                Все мессенджеры <ChevronDown size={14} />
              </button>
              <button className="flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 text-slate-500">
                <Filter size={14} />
              </button>
            </div>
          </div>

          {d.messages.map((m) => (
            <div key={m.time} className="mt-3 rounded-xl bg-slate-50 p-3">
              <div className="flex items-center gap-2 text-sm">
                <span
                  className="flex h-5 w-5 items-center justify-center rounded-full"
                  style={{ backgroundColor: "#25D36622", color: "#25D366" }}
                >
                  <FaWhatsapp size={12} />
                </span>
                <span className="font-medium text-ink">{m.from}</span>
                <span className="text-muted">• {m.time}</span>
              </div>
              <p className="mt-1.5 text-sm text-slate-600">
                {m.text} <button className="font-medium text-brand-600">Ещё</button>
              </p>
            </div>
          ))}

          <div className="mt-3 flex items-center gap-2">
            <input
              placeholder="Написать сообщение..."
              className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:border-brand"
            />
            <button className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand text-white">
              <Send size={16} />
            </button>
          </div>
        </div>

        {/* Фокус / Приоритет */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <button className="flex items-center justify-center gap-2 rounded-xl bg-blue-50 py-3 font-medium text-brand-600">
            <Target size={18} /> Фокус
          </button>
          <button className="flex items-center justify-center gap-2 rounded-xl bg-amber-50 py-3 font-medium text-amber-600">
            <Flag size={18} /> Приоритет
          </button>
        </div>

        {/* Каналы */}
        <div className="mt-5">
          <ChannelButtons />
        </div>
      </div>
    </div>
  );
}
