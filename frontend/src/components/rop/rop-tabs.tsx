import clsx from "clsx";
import Link from "next/link";

/** Под-навигация раздела РОП. Построенные экраны кликабельны, остальные — заглушки
 * («скоро», как пункты-заглушки в сайдбаре). «Канбан» ведёт на доску сделок CRM. */
const TABS: { key: string; label: string; href?: string }[] = [
  { key: "kanban", label: "Канбан", href: "/crm/deals" },
  { key: "overview", label: "Обзор РОП", href: "/crm/rop" },
  { key: "scoreboard", label: "Скорборд", href: "/crm/rop/scoreboard" },
  { key: "planning", label: "Планирование", href: "/crm/rop/planning" },
  { key: "pace", label: "Темп", href: "/crm/rop/pace" },
  { key: "cash", label: "Деньги", href: "/crm/rop/cash" },
  { key: "activity", label: "Активность", href: "/crm/rop/activity" },
  { key: "stages", label: "Этапы", href: "/crm/rop/stages" },
  { key: "loss", label: "Ревью проигрышей", href: "/crm/rop/loss-review" },
];

export function RopTabs({
  active,
}: {
  active: "overview" | "scoreboard" | "planning" | "pace" | "cash" | "activity" | "stages" | "loss";
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-line">
      {TABS.map((t) => {
        if (!t.href) {
          return (
            <span
              key={t.key}
              title="Раздел в разработке"
              className="cursor-default px-3 py-2 text-sm text-faint"
            >
              {t.label}
              <span className="ml-1 align-super text-[9px]">скоро</span>
            </span>
          );
        }
        const isActive = t.key === active;
        return (
          <Link
            key={t.key}
            href={t.href}
            className={clsx(
              "relative px-3 py-2 text-sm",
              isActive ? "font-semibold text-accent-ink" : "text-muted hover:text-ink",
            )}
          >
            {t.label}
            {isActive && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-accent" />}
          </Link>
        );
      })}
    </div>
  );
}
