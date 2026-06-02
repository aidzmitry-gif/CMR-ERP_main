import clsx from "clsx";
import { Calendar, Flag, MoreHorizontal, Pencil, Star, Target, User } from "lucide-react";
import Link from "next/link";
import { ChannelRow } from "@/components/channels";
import { PriorityBadge } from "@/components/priority-badge";
import { formatMoney } from "@/lib/format";
import type { Deal } from "@/lib/types";

export function DealCard({ deal }: { deal: Deal }) {
  const sideDate = deal.date ?? deal.closedDate;

  return (
    <Link
      href={`/crm/deals/${deal.id}`}
      className="block rounded-xl bg-white p-3.5 shadow-card transition-shadow hover:shadow-pop"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted">№ {deal.number}</span>
        <div className="flex items-center gap-1.5">
          <PriorityBadge priority={deal.priority} />
          <Star
            size={14}
            className={clsx(deal.starred ? "fill-amber-400 text-amber-400" : "text-slate-300")}
          />
          <MoreHorizontal size={15} className="text-slate-400" />
        </div>
      </div>

      <div className="mt-2 font-semibold text-ink">{deal.company}</div>
      <div className="text-xs text-muted">{deal.description}</div>
      <div className="mt-2 font-semibold text-ink">{formatMoney(deal.amount)}</div>

      {deal.todo ? (
        <div className="mt-2 space-y-1 rounded-lg bg-slate-50 p-2.5 text-xs text-slate-500">
          <div className="font-medium text-slate-600">Что нужно сделать:</div>
          <div>{deal.todo}</div>
          <div className="flex justify-between">
            <span>Время действия:</span>
            <span className="text-slate-600">{deal.actionTime}</span>
          </div>
          <div className="flex justify-between">
            <span>Дата действия:</span>
            <span className="text-slate-600">{deal.actionDate}</span>
          </div>
          <div className="pt-0.5 text-slate-600">
            Номенклатура: {deal.itemsLabel}, {deal.itemsCount} поз.
          </div>
          <span className="inline-flex items-center gap-1 pt-0.5 text-brand-600">
            <Pencil size={12} /> Редактировать товар
          </span>
        </div>
      ) : deal.closedDate ? (
        <div className="mt-2 text-xs text-muted">
          Дата закрытия: <span className="text-slate-700">{deal.closedDate}</span>
        </div>
      ) : (
        <div className="mt-2 text-xs text-muted">
          След. шаг: <span className="text-slate-700">{deal.nextStep}</span>
        </div>
      )}

      <div className="mt-2 flex items-center justify-between text-xs text-muted">
        <span className="inline-flex items-center gap-1">
          <User size={13} /> {deal.owner}
        </span>
        {sideDate && (
          <span className="inline-flex items-center gap-1">
            <Calendar size={12} /> {sideDate}
          </span>
        )}
      </div>

      <div className="mt-2.5 flex gap-2">
        <span className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-200 py-1.5 text-xs font-medium text-slate-600">
          <Target size={13} className="text-brand-600" /> Фокус
        </span>
        <span className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-200 py-1.5 text-xs font-medium text-slate-600">
          <Flag size={13} className="text-amber-500" /> Приоритет
        </span>
      </div>

      <div className="mt-2.5 border-t border-slate-100 pt-2.5">
        <ChannelRow />
      </div>
    </Link>
  );
}
