"use client";

import clsx from "clsx";
import {
  BarChart3,
  Boxes,
  Box,
  ClipboardList,
  Factory,
  GraduationCap,
  Headphones,
  Home,
  Megaphone,
  Scale,
  Settings,
  ShoppingCart,
  Truck,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type IconCmp = React.ComponentType<{ size?: number }>;

interface SubItem {
  label: string;
  href?: string;
}

interface ModuleItem {
  label: string;
  Icon: IconCmp;
  href?: string;
  sub?: SubItem[];
}

// Подразделы модулей — как в референсах: у активного модуля раскрывается подменю.
// Первый пункт ведёт на страницу-воронку, остальные — заглушки (раздел в разработке).
const MODULES: ModuleItem[] = [
  { label: "Главная", Icon: Home, href: "/crm/owner" },
  {
    label: "CRM",
    Icon: Workflow,
    sub: [
      { label: "Продажи" },
      { label: "Лиды", href: "/crm/leads" },
      { label: "Клиенты" },
      { label: "Контакты" },
      { label: "Сделки", href: "/crm/deals" },
    ],
  },
  {
    label: "Закупки",
    Icon: ShoppingCart,
    href: "/erp/procurement",
    sub: [
      { label: "Воронка закупок", href: "/erp/procurement" },
      { label: "Поставщики" },
      { label: "Номенклатура · SKU" },
      { label: "Документы" },
      { label: "AI-агенты" },
      { label: "Аналитика" },
    ],
  },
  {
    label: "Производство",
    Icon: Factory,
    href: "/erp/production",
    sub: [
      { label: "Канбан цеха", href: "/erp/production" },
      { label: "Наряды · заказы" },
      { label: "Маршруты" },
      { label: "Спецификации · BOM" },
      { label: "ОТК · Контроль" },
      { label: "Оборудование" },
    ],
  },
  {
    label: "Склад",
    Icon: Boxes,
    href: "/erp/wms",
    sub: [
      { label: "Операции", href: "/erp/wms" },
      { label: "Поступления" },
      { label: "Размещение" },
      { label: "Остатки" },
      { label: "Инвентаризация" },
    ],
  },
  { label: "Логистика", Icon: Truck, href: "/erp/logistics" },
  { label: "Финансы", Icon: Wallet, href: "/erp/finance" },
  { label: "Маркетинг", Icon: Megaphone, href: "/erp/marketing" },
  { label: "Сервис и поддержка", Icon: Headphones, href: "/erp/service" },
  {
    label: "HR",
    Icon: Users,
    href: "/erp/hr",
    sub: [
      { label: "Подбор персонала", href: "/erp/hr" },
      { label: "Сотрудники" },
      { label: "Адаптация" },
      { label: "Обучение и KPI" },
      { label: "Кадровый учёт" },
    ],
  },
  {
    label: "Офис-менеджер",
    Icon: ClipboardList,
    href: "/erp/office",
    sub: [
      { label: "Документы по сделкам", href: "/erp/office" },
      { label: "Отгрузки" },
      { label: "Контроль оплаты" },
      { label: "Архив" },
    ],
  },
  {
    label: "Юр. отдел",
    Icon: Scale,
    href: "/erp/legal",
    sub: [
      { label: "Контроль документов", href: "/erp/legal" },
      { label: "Договоры" },
      { label: "Претензии" },
      { label: "Судебные дела" },
    ],
  },
  {
    label: "База знаний",
    Icon: GraduationCap,
    href: "/erp/knowledge",
    sub: [
      { label: "Обучение", href: "/erp/knowledge" },
      { label: "Курсы" },
      { label: "Сертификаты" },
      { label: "Достижения" },
    ],
  },
  { label: "Аналитика", Icon: BarChart3, href: "/erp/analytics" },
  { label: "IT и настройки", Icon: Settings, href: "/erp/settings" },
];

// Пользователь/роль в подвале меню зависит от активного модуля (как в референсах).
const USERS: { prefix: string; name: string; role: string }[] = [
  { prefix: "/erp/procurement", name: "Иван Петров", role: "Руководитель закупок" },
  { prefix: "/erp/production", name: "Сидоров А.С.", role: "Начальник производства" },
  { prefix: "/erp/wms", name: "Сидоров С.С.", role: "Заведующий складом" },
  { prefix: "/erp/hr", name: "Соколова А.", role: "HR-менеджер" },
  { prefix: "/erp/office", name: "Ольга Кравцова", role: "Офис-менеджер" },
  { prefix: "/erp/legal", name: "Ирина Петрова", role: "Юрисконсульт" },
  { prefix: "/erp/knowledge", name: "Иван Петров", role: "Сотрудник" },
];
const DEFAULT_USER = { name: "Иван Петров", role: "Администратор" };

function userInitials(name: string): string {
  return name
    .replace(/[«».]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

export function Sidebar() {
  const pathname = usePathname() || "";
  const crmActive = pathname.startsWith("/crm/deals") || pathname.startsWith("/crm/leads");
  const user = USERS.find((u) => pathname.startsWith(u.prefix)) ?? DEFAULT_USER;

  function moduleActive(m: ModuleItem): boolean {
    if (m.label === "CRM") return crmActive;
    return !!m.href && pathname === m.href;
  }

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
          const active = moduleActive(m);
          const cls = clsx(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
            active ? "bg-brand-100 text-brand-600" : "text-slate-600 hover:bg-slate-50",
          );
          return (
            <div key={m.label}>
              {m.href ? (
                <Link href={m.href} className={cls}>
                  <m.Icon size={18} />
                  {m.label}
                </Link>
              ) : (
                <div className={`${cls} cursor-default`} title="Модуль">
                  <m.Icon size={18} />
                  {m.label}
                </div>
              )}
              {m.sub && active && (
                <div className="mb-1 mt-1 flex flex-col">
                  {m.sub.map((s) => {
                    const sactive = !!s.href && pathname === s.href;
                    const scls = clsx(
                      "rounded-lg py-1.5 pl-11 pr-3 text-sm",
                      sactive ? "font-medium text-brand-600" : "text-slate-500 hover:bg-slate-50",
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
          {userInitials(user.name)}
        </span>
        <div className="leading-tight">
          <div className="text-sm font-medium text-ink">{user.name}</div>
          <div className="text-xs text-muted">{user.role}</div>
        </div>
      </div>
    </aside>
  );
}
