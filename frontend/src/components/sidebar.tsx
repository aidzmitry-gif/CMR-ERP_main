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
import { LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

type IconCmp = React.ComponentType<{ size?: number }>;

interface SubItem {
  label: string;
  href?: string;
}

interface ModuleItem {
  // UI-слаг модуля = ключ матрицы доступа (config/access.py); по нему прячем недоступное
  slug: string;
  label: string;
  Icon: IconCmp;
  href?: string;
  sub?: SubItem[];
}

// Подразделы модулей — как в референсах: у активного модуля раскрывается подменю.
// Первый пункт ведёт на страницу-воронку, остальные — заглушки (раздел в разработке).
const MODULES: ModuleItem[] = [
  { slug: "home", label: "Главная", Icon: Home, href: "/crm/owner" },
  {
    slug: "crm",
    label: "CRM",
    Icon: Workflow,
    href: "/crm/deals",
    sub: [
      { label: "Продажи" },
      { label: "Лиды", href: "/crm/leads" },
      { label: "Клиенты" },
      { label: "Контакты" },
      { label: "Сделки", href: "/crm/deals" },
      { label: "РОП · Обзор", href: "/crm/rop" },
      { label: "РОП · Планирование", href: "/crm/rop/planning" },
      { label: "РОП · Темп", href: "/crm/rop/pace" },
      { label: "РОП · Деньги · дебиторка", href: "/crm/rop/cash" },
      { label: "РОП · Активность", href: "/crm/rop/activity" },
      { label: "РОП · Этапы воронки", href: "/crm/rop/stages" },
      { label: "РОП · Ревью проигрышей", href: "/crm/rop/loss-review" },
    ],
  },
  {
    slug: "procurement",
    label: "Закупки",
    Icon: ShoppingCart,
    href: "/erp/procurement",
    sub: [
      { label: "Воронка закупок", href: "/erp/procurement" },
      { label: "Поставщики" },
      { label: "Претензии поставщикам", href: "/erp/procurement/claims" },
      { label: "Номенклатура · SKU" },
      { label: "Документы" },
      { label: "AI-агенты" },
      { label: "Аналитика" },
    ],
  },
  {
    slug: "production",
    label: "Производство",
    Icon: Factory,
    href: "/erp/production",
    sub: [
      { label: "Канбан цеха", href: "/erp/production" },
      { label: "Заявки на сборку", href: "/erp/production/zayavki" },
      { label: "Нормы и нормативы", href: "/erp/production/norms" },
      { label: "Выработка и оценка", href: "/erp/production/vyrabotka" },
      { label: "ОТК · Контроль", href: "/erp/production/otk" },
      { label: "Спецификации · BOM", href: "/erp/production/bom" },
      { label: "Планирование · план/факт", href: "/erp/production/planning" },
      { label: "Аналитика производства", href: "/erp/production/analytics" },
      { label: "Наряды · заказы" },
      { label: "Маршруты" },
      { label: "Оборудование" },
    ],
  },
  {
    slug: "wms",
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
  { slug: "logistics", label: "Логистика", Icon: Truck, href: "/erp/logistics" },
  { slug: "finance", label: "Финансы", Icon: Wallet, href: "/erp/finance" },
  { slug: "marketing", label: "Маркетинг", Icon: Megaphone, href: "/erp/marketing" },
  { slug: "service", label: "Сервис и поддержка", Icon: Headphones, href: "/erp/service" },
  {
    slug: "hr",
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
    slug: "office",
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
    slug: "legal",
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
    slug: "knowledge",
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
  { slug: "analytics", label: "Аналитика", Icon: BarChart3, href: "/erp/analytics" },
  { slug: "it", label: "IT и настройки", Icon: Settings, href: "/erp/settings" },
];

function initials(name: string): string {
  return name
    .replace(/[«».·/]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

interface SidebarProps {
  // доступные UI-слаги модулей для текущей роли; null/undefined → показывать все
  // (backend недоступен или standalone-рендер). Источник — матрица config/access.py.
  allowedSlugs?: string[] | null;
  userName?: string;
  roleTitle?: string;
}

export function Sidebar({ allowedSlugs, userName, roleTitle }: SidebarProps = {}) {
  const pathname = usePathname() || "";
  const router = useRouter();
  const crmActive =
    pathname.startsWith("/crm/deals") ||
    pathname.startsWith("/crm/leads") ||
    pathname.startsWith("/crm/rop");

  // dev-выход: чистим cookie сессии и уводим на экран входа
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  const visible =
    allowedSlugs == null ? MODULES : MODULES.filter((m) => allowedSlugs.includes(m.slug));

  function moduleActive(m: ModuleItem): boolean {
    if (m.slug === "crm") return crmActive;
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
        {visible.map((m) => {
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

      {/* профиль вошедшего сотрудника + выход (dev-логин; реальный — Keycloak, часть 5) */}
      {userName && (
        <div className="flex items-center gap-3 border-t border-slate-200 px-4 py-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-xs font-semibold text-white">
            {initials(userName)}
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-sm font-medium text-ink">{userName}</div>
            <div className="truncate text-xs text-muted">{roleTitle ?? "—"}</div>
          </div>
          <button
            type="button"
            onClick={logout}
            aria-label="Выйти"
            title="Выйти"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-50 hover:text-slate-600"
          >
            <LogOut size={16} />
          </button>
        </div>
      )}
    </aside>
  );
}
