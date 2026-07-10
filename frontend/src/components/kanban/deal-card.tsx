import clsx from "clsx";
import { Calendar, Flag, MoreHorizontal, Pencil, Phone, Star, Target, User } from "lucide-react";
import Link from "next/link";
import { ChannelRow } from "@/components/channels";
import { PriorityBadge } from "@/components/priority-badge";
import { formatMoney } from "@/lib/format";
import type { Deal } from "@/lib/types";

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

/** Карточка сделки на канбане. Бейджи/плашки Сделки 2.0 (дни в стадии SALES-43,
 * вероятность·взвешенно SALES-44, причина отказа SALES-40) рендерятся только когда
 * вызывающий передал соответствующий проп — иначе карточка ведёт себя как раньше.
 *
 * Кнопки «Позвонить»/«Отказ» — ВНЕ <Link>: вложенный <button> в <a> ломает клик
 * в браузерах; drag&drop на доске глушит через onPointerDown stopPropagation. */
export function DealCard({
  deal,
  days = null,
  stuck = false,
  probability,
  weighted,
  lostReasonTitle,
  wonResult = false,
  onLose,
  onCall,
  fmt = formatMoney,
}: {
  deal: Deal;
  days?: number | null;
  stuck?: boolean;
  probability?: number;
  weighted?: number;
  lostReasonTitle?: string;
  wonResult?: boolean;
  onLose?: () => void;
  /** Открыть окно звонка прямо с карточки (без захода в drawer-preview). */
  onCall?: () => void;
  fmt?: (value: number) => string;
}) {
  const sideDate = deal.date ?? deal.closedDate;

  function stopDrag(e: React.SyntheticEvent) {
    e.stopPropagation();
  }

  return (
    <div className="group rounded-xl bg-surface p-3.5 shadow-card transition-shadow hover:shadow-pop">
      <Link href={`/crm/deals/${deal.id}`} className="block">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">№ {deal.number}</span>
          <div className="flex items-center gap-1.5">
            <PriorityBadge priority={deal.priority} />
            {days != null && (
              <span
                className={clsx(
                  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold",
                  stuck ? "bg-amber-100 text-amber-700" : "bg-sunken text-muted",
                )}
              >
                🕒 {days} дн.
              </span>
            )}
            {deal.supplyArrivedAt && (
              <span
                title={`Под приход: ${deal.supplyArrivedSku ?? "товар"} · пришёл ${formatShortDate(deal.supplyArrivedAt)}`}
                className="inline-flex items-center gap-1 rounded-[5px] bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700"
              >
                🚚 {formatShortDate(deal.supplyArrivedAt)}
              </span>
            )}
            <Star
              size={14}
              className={clsx(deal.starred ? "fill-amber-400 text-amber-400" : "text-faint")}
            />
            <MoreHorizontal size={15} className="text-faint" />
          </div>
        </div>

        <div className="mt-2 font-semibold text-ink">{deal.company}</div>
        <div className="text-xs text-muted">{deal.description}</div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{fmt(deal.amount)}</span>
          {probability != null && probability > 0 && weighted != null && (
            <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold text-accent-ink">
              {probability}% · ≈ {fmt(weighted)}
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
          <div className="mt-2 space-y-1 rounded-lg bg-sunken p-2.5 text-xs text-muted">
            <div className="font-medium text-muted">Что нужно сделать:</div>
            <div>{deal.todo}</div>
            <div className="flex justify-between">
              <span>Время действия:</span>
              <span className="text-ink">{deal.actionTime}</span>
            </div>
            <div className="flex justify-between">
              <span>Дата действия:</span>
              <span className="text-ink">{deal.actionDate}</span>
            </div>
            <div className="pt-0.5 text-muted">
              Номенклатура: {deal.itemsLabel}, {deal.itemsCount} поз.
            </div>
            <span className="inline-flex items-center gap-1 pt-0.5 text-accent-ink">
              <Pencil size={12} /> Редактировать товар
            </span>
          </div>
        ) : deal.closedDate ? (
          <div className="mt-2 text-xs text-muted">
            Дата закрытия: <span className="text-ink">{deal.closedDate}</span>
          </div>
        ) : (
          <div className="mt-2 text-xs text-muted">
            След. шаг: <span className="text-ink">{deal.nextStep}</span>
          </div>
        )}
      </Link>

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
          {onCall && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                stopDrag(e);
                onCall();
              }}
              onPointerDown={stopDrag}
              title="Позвонить — окно звонка"
              aria-label="Позвонить"
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold text-money hover:bg-money-soft"
            >
              <Phone size={13} />
            </button>
          )}
          {onLose && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                stopDrag(e);
                onLose();
              }}
              onPointerDown={stopDrag}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold text-red-700 hover:bg-red-100"
            >
              ✕ Отказ
            </button>
          )}
        </div>
      </div>

      <div className="mt-2.5 flex gap-2">
        <span className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line py-1.5 text-xs font-medium text-muted">
          <Target size={13} className="text-accent-ink" /> Фокус
        </span>
        <span className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line py-1.5 text-xs font-medium text-muted">
          <Flag size={13} className="text-amber-500" /> Приоритет
        </span>
      </div>

      <div className="mt-2.5 border-t border-line pt-2.5">
        <ChannelRow onPhone={onCall} />
      </div>
    </div>
  );
}
