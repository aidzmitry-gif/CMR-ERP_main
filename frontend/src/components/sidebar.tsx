import clsx from "clsx";
import {
  BarChart3,
  Boxes,
  Box,
  Factory,
  Headphones,
  Home,
  Megaphone,
  Settings,
  ShoppingCart,
  Truck,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";
import Link from "next/link";

type IconCmp = React.ComponentType<{ size?: number }>;

interface ModuleItem {
  label: string;
  Icon: IconCmp;
  active?: boolean;
  href?: string;
  sub?: { label: string; active?: boolean; href?: string }[];
}

const MODULES: ModuleItem[] = [
  { label: "Главная", Icon: Home, href: "/crm/owner" },
  {
    label: "CRM",
    Icon: Workflow,
    active: true,
    sub: [
      { label: "Продажи" },
      { label: "Клиенты" },
      { label: "Контакты" },
      { label: "Сделки", active: true, href: "/crm/deals" },
    ],
  },
  { label: "Закупки", Icon: ShoppingCart, href: "/erp/procurement" },
  { label: "Производство", Icon: Factory, href: "/erp/production" },
  { label: "Склад", Icon: Boxes, href: "/erp/wms" },
  { label: "Логистика", Icon: Truck, href: "/erp/logistics" },
  { label: "Финансы", Icon: Wallet, href: "/erp/finance" },
  { label: "Маркетинг", Icon: Megaphone, href: "/erp/marketing" },
  { label: "Сервис и поддержка", Icon: Headphones, href: "/erp/service" },
  { label: "HR", Icon: Users, href: "/erp/hr" },
  { label: "Аналитика", Icon: BarChart3, href: "/erp/analytics" },
  { label: "IT и настройки", Icon: Settings, href: "/erp/settings" },
];

export function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
      {/* лого */}
      <div className="flex items-center gap-2 px-5 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand text-white">
          <Box size={20} />
        </span>
        <span className="text-lg font-bold text-ink">ERP</span>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4 thin-scroll">
        <div className="px-3 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          Модули
        </div>
        {MODULES.map((m) => {
          const cls = clsx(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
            m.active ? "bg-brand-100 text-brand-600" : "text-slate-600 hover:bg-slate-50",
          );
          return (
            <div key={m.label}>
              {m.href ? (
                <Link href={m.href} className={cls}>
                  <m.Icon size={18} />
                  {m.label}
                </Link>
              ) : (
                <div className={`${cls} cursor-default`} title="Модуль в разработке">
                  <m.Icon size={18} />
                  {m.label}
                </div>
              )}
              {m.sub && (
                <div className="mb-1 mt-1 flex flex-col">
                  {m.sub.map((s) => {
                    const scls = clsx(
                      "rounded-lg py-1.5 pl-11 pr-3 text-sm",
                      s.active ? "font-medium text-brand-600" : "text-slate-500 hover:bg-slate-50",
                    );
                    return s.href ? (
                      <Link key={s.label} href={s.href} className={scls}>
                        {s.label}
                      </Link>
                    ) : (
                      <div key={s.label} className={`${scls} cursor-default`} title="Раздел в разработке">
                        {s.label}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      {/* профиль */}
      <div className="flex items-center gap-3 border-t border-slate-200 px-4 py-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-xs font-semibold text-white">
          ИП
        </span>
        <div className="leading-tight">
          <div className="text-sm font-medium text-ink">Иван Петров</div>
          <div className="text-xs text-muted">Администратор</div>
        </div>
      </div>
    </aside>
  );
}
