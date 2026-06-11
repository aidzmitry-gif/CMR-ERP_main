import clsx from "clsx";
import { Calendar, Flag, MoreHorizontal, Pencil, Star, Target, User } from "lucide-react";
import Link from "next/link";
import { ChannelRow } from "@/components/channels";
import { PriorityBadge } from "@/components/priority-badge";
import { formatMoney } from "@/lib/format";
import type { Deal } from "@/lib/types";

/** Карточка сделки на канбане. Бейджи/плашки Сделки 2.0 (дни в стадии SALES-43,
 * вероятность·взвешенно SALES-44, причина отказа SALES-40) рендерятся только когда
 * вызывающий передал соответствующий проп — иначе карточка ведёт себя как раньше. */
export function DealCard({
  deal,
  days = null,
  stuck = false,
  probability,
  weighted,
  lostReasonTitle,
  wonResult = false,
  onLose,
}: {
  deal: Deal;
  days?: number | null;
  stuck?: boolean;
  probability?: number;
  weighted?: number;
  lostReasonTitle?: string;
  wonResult?: boolean;
  onLose?: () => void;
}) {
  const sideDate = deal.date ?? deal.closedDate;

  return (
    <Link
      href={`/crm/deals/${deal.id}`}
      className="group block rounded-xl bg-white p-3.5 shadow-card transition-shadow hover:shadow-pop"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted">№ {deal.number}</span>
        <div className="flex items-center gap-1.5">
          <PriorityBadge priority={deal.priority} />
          {days != null && (
            <span
              className={clsx(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold",
                stuck ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500",
              )}
            >
              🕒 {days} дн.
            </span>
          )}
          <Star
            size={14}
            className={clsx(deal.starred ? "fill-amber-400 text-amber-400" : "text-slate-300")}
          />
          <MoreHorizontal size={15} className="text-slate-400" />
        </div>
      </div>

      <div className="mt-2 font-semibold text-ink">{deal.company}</div>
      <div className="text-xs text-muted">{deal.description}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="font-semibold text-ink">{formatMoney(deal.amount)}</span>
        {probability != null && probability > 0 && weighted != null && (
          <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[11px] font-semibold text-brand-700">
            {probability}% · ≈ {formatMoney(weighted)}
          </span>
        )}
      </div>

      {lostReasonTitle ? (
        <div className="mt-2">
          <span className="inline-block rounded-md bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700">
            Причина: {lostReasonTitle}
          </span>
        </div>
      ) : wonResult ? (
        <div className="mt-2">
          <span className="inline-block rounded-md bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">
            ✓ Сделка выиграна
          </span>
        </div>
      ) : null}

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
        <div className="flex items-center gap-2">
          {sideDate && (
            <span className="inline-flex items-center gap-1">
              <Calendar size={12} /> {sideDate}
            </span>
          )}
          {onLose && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onLose();
              }}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold text-red-700 opacity-0 transition-opacity hover:bg-red-100 group-hover:opacity-100"
            >
              ✕ Отказ
            </button>
          )}
        </div>
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
