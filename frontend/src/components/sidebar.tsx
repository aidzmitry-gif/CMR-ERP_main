"use client";

import clsx from "clsx";
import {
  BarChart3,
  Boxes,
  Box,
  ClipboardList,
  Factory,
  GraduationCap,
  GripVertical,
  Headphones,
  Home,
  Library,
  LogOut,
  Megaphone,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Scale,
  Settings,
  ShoppingCart,
  Truck,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

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
      { label: "Звонки", href: "/crm/calls" },
      { label: "Каталог · подбор", href: "/crm/catalog" },
      { label: "Реестр документов", href: "/crm/docs" },
      { label: "Архив документов", href: "/crm/docs-archive" },
      { label: "Постоянные клиенты", href: "/crm/regular" },
      { label: "Статус отгрузки", href: "/crm/shipments" },
      { label: "Валовая прибыль", href: "/crm/margin" },
      { label: "Конструктор плана", href: "/crm/plan" },
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
      { label: "Движения", href: "/erp/wms/movements" },
      { label: "Размещение", href: "/erp/wms/locations" },
      { label: "Остатки 1С", href: "/erp/wms/stock" },
      { label: "Остаток (движения)", href: "/erp/wms/balances" },
      { label: "Инвентаризация", href: "/erp/wms/inventory" },
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
  {
    slug: "spravochniki",
    label: "Справочники",
    Icon: Library,
    href: "/erp/spravochniki",
    sub: [
      { label: "Каталог", href: "/erp/spravochniki" },
      { label: "Курсы валют · НДС", href: "/erp/spravochniki/rates" },
      { label: "Дедупликация", href: "/erp/spravochniki/merge" },
      { label: "Группы номенклатуры", href: "/erp/spravochniki/categories" },
      { label: "Импорт из 1С", href: "/erp/spravochniki/import" },
      { label: "Доступ AI", href: "/erp/spravochniki/ai" },
    ],
  },
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

// localStorage-ключи пользовательских настроек сайдбара.
// TODO(Step B): collapsed → cookie (как THEME_INIT_SCRIPT), уберёт width-флэш при первой отрисовке.
const ORDER_KEY = "aios-sidebar-order"; // порядок модулей (массив slugs)
const COLLAPSED_KEY = "aios-sidebar-collapsed"; // "1" — свёрнут rail
const LOGO_KEY = "aios-sidebar-logo"; // текст логотипа (по умолч. "ERP")
const SUBORDER_KEY = "aios-sidebar-sub-order"; // порядок sub-items: { [moduleSlug]: string[] }

function readOrder(): string[] | null {
  try {
    const raw = localStorage.getItem(ORDER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((s) => typeof s === "string") : null;
  } catch {
    return null;
  }
}

function writeOrder(order: string[]) {
  try {
    localStorage.setItem(ORDER_KEY, JSON.stringify(order));
  } catch {
    /* приватный режим — просто не сохраняем */
  }
}

function readLogo(): string {
  try {
    return localStorage.getItem(LOGO_KEY) || "ERP";
  } catch {
    return "ERP";
  }
}

function writeLogo(text: string) {
  try {
    localStorage.setItem(LOGO_KEY, text);
  } catch {
    /* */
  }
}

function readSubOrder(): Record<string, string[]> {
  try {
    const raw = localStorage.getItem(SUBORDER_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeSubOrder(order: Record<string, string[]>) {
  try {
    localStorage.setItem(SUBORDER_KEY, JSON.stringify(order));
  } catch {
    /* */
  }
}

function applyOrder(modules: ModuleItem[], order: string[] | null): ModuleItem[] {
  if (!order || order.length === 0) return modules;
  const bySlug = new Map(modules.map((m) => [m.slug, m]));
  const placed = order.map((s) => bySlug.get(s)).filter((m): m is ModuleItem => Boolean(m));
  const placedSet = new Set(placed.map((m) => m.slug));
  const tail = modules.filter((m) => !placedSet.has(m.slug)); // новые модули — в конец
  return [...placed, ...tail];
}

function applySubOrder(items: SubItem[], order: string[] | undefined): SubItem[] {
  if (!order || order.length === 0) return items;
  const byLabel = new Map(items.map((s) => [s.label, s]));
  const placed = order.map((l) => byLabel.get(l)).filter((s): s is SubItem => Boolean(s));
  const placedSet = new Set(placed.map((s) => s.label));
  const tail = items.filter((s) => !placedSet.has(s.label));
  return [...placed, ...tail];
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

  // collapsed (rail) — пользовательский тоггл, в localStorage.
  // hoverExpanded — временное раскрытие при наведении (overlay, не толкает контент).
  // editing — режим перестановки разделов: drag-handles появляются у модулей И sub-items,
  //   ссылки временно отключены, чтобы случайно не перейти при перетаскивании.
  // order — пользовательский порядок модулей; null → дефолт (как в MODULES).
  // subOrder — порядок sub-items по slug модуля; {} → дефолт (как в MODULES[i].sub).
  // logoText — кастомный текст логотипа («ERP» по умолчанию); пользователь
  //   редактирует кликом по логотипу. TODO(Step B): загрузка изображения.
  const [collapsed, setCollapsed] = useState(false);
  const [hoverExpanded, setHoverExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [order, setOrder] = useState<string[] | null>(null);
  const [subOrder, setSubOrder] = useState<Record<string, string[]>>({});
  const [draggingSlug, setDraggingSlug] = useState<string | null>(null);
  const [draggingSub, setDraggingSub] = useState<{ module: string; label: string } | null>(null);
  const [logoText, setLogoText] = useState("ERP");
  const [logoEditing, setLogoEditing] = useState(false);
  const [logoDraft, setLogoDraft] = useState("ERP");
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Состояние читаем после маунта — иначе SSR vs клиент-гидрация рассогласуется.
  // Гидрация из localStorage (внешнее хранилище) — легитимный setState в эффекте.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "1");
    } catch {
      /* */
    }
    setOrder(readOrder());
    setSubOrder(readSubOrder());
    const lg = readLogo();
    setLogoText(lg);
    setLogoDraft(lg);
    // Cleanup hoverTimer на unmount — иначе 120мс таймер может выстрелить
    // в уже размонтированный компонент и вызвать React-warning.
    return () => {
      if (hoverTimer.current) clearTimeout(hoverTimer.current);
    };
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Применяем пользовательский порядок + фильтр по правам.
  const visibleModules = useMemo(() => {
    const ordered = applyOrder(MODULES, order);
    return allowedSlugs == null ? ordered : ordered.filter((m) => allowedSlugs.includes(m.slug));
  }, [order, allowedSlugs]);

  const crmActive =
    pathname.startsWith("/crm/deals") ||
    pathname.startsWith("/crm/leads") ||
    pathname.startsWith("/crm/calls") ||
    pathname.startsWith("/crm/catalog") ||
    pathname.startsWith("/crm/docs") ||
    pathname.startsWith("/crm/regular") ||
    pathname.startsWith("/crm/shipments") ||
    pathname.startsWith("/crm/margin") ||
    pathname.startsWith("/crm/plan") ||
    pathname.startsWith("/crm/rop");

  // dev-выход: чистим cookie сессии и уводим на экран входа
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  function moduleActive(m: ModuleItem): boolean {
    if (m.slug === "crm") return crmActive;
    return !!m.href && pathname === m.href;
  }

  // ─── Collapse / hover-expand ────────────────────────────────────────────────
  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    setHoverExpanded(false);
    if (next) setEditing(false); // в свёрнутом режиме не редактируем порядок
    try {
      localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      /* */
    }
  }

  function onMouseEnter() {
    if (!collapsed) return;
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setHoverExpanded(true), 120);
  }

  function onMouseLeave() {
    if (hoverTimer.current) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    setHoverExpanded(false);
  }

  const showFull = !collapsed || hoverExpanded;
  const layoutWidth = collapsed ? "w-14" : "w-60"; // layout-placeholder
  const contentWidth = showFull ? "w-60" : "w-14"; // visible-ширина

  // ─── Logo editing ───────────────────────────────────────────────────────────
  function commitLogo() {
    const next = logoDraft.trim() || "ERP";
    setLogoText(next);
    setLogoDraft(next);
    writeLogo(next);
    setLogoEditing(false);
  }
  function cancelLogo() {
    setLogoDraft(logoText);
    setLogoEditing(false);
  }

  // ─── DnD: модули ────────────────────────────────────────────────────────────
  // Стратегия: каждый module-row draggable. При onDragOver разрешаем drop,
  // при onDrop переставляем массив видимых модулей, скрытые-по-роли складываем
  // в конец полного порядка (чтобы не терялись при смене роли), сохраняем в LS.
  function handleDragStart(slug: string) {
    return (e: React.DragEvent) => {
      if (!editing) {
        e.preventDefault();
        return;
      }
      setDraggingSlug(slug);
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "module:" + slug);
    };
  }

  function handleDragOver(slug: string) {
    return (e: React.DragEvent) => {
      if (!editing || !draggingSlug || slug === draggingSlug) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    };
  }

  function handleDrop(slug: string) {
    return (e: React.DragEvent) => {
      e.preventDefault();
      if (!editing || !draggingSlug || draggingSlug === slug) return;
      const ids = visibleModules.map((m) => m.slug);
      const from = ids.indexOf(draggingSlug);
      const to = ids.indexOf(slug);
      if (from < 0 || to < 0) return;
      const next = [...ids];
      next.splice(from, 1);
      next.splice(to, 0, draggingSlug);
      const nextSet = new Set(next);
      const hidden = MODULES.filter((m) => !nextSet.has(m.slug)).map((m) => m.slug);
      const fullOrder = [...next, ...hidden];
      setOrder(fullOrder);
      writeOrder(fullOrder);
      setDraggingSlug(null);
    };
  }

  function handleDragEnd() {
    setDraggingSlug(null);
  }

  // ─── DnD: sub-items (в рамках активного модуля) ─────────────────────────────
  function handleSubDragStart(moduleSlug: string, label: string) {
    return (e: React.DragEvent) => {
      if (!editing) {
        e.preventDefault();
        return;
      }
      e.stopPropagation(); // не пускаем dragstart на parent-модуль
      setDraggingSub({ module: moduleSlug, label });
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "sub:" + moduleSlug + ":" + label);
    };
  }

  function handleSubDragOver(moduleSlug: string, label: string) {
    return (e: React.DragEvent) => {
      if (
        !editing ||
        !draggingSub ||
        draggingSub.module !== moduleSlug ||
        draggingSub.label === label
      )
        return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "move";
    };
  }

  function handleSubDrop(moduleSlug: string, label: string) {
    return (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (
        !editing ||
        !draggingSub ||
        draggingSub.module !== moduleSlug ||
        draggingSub.label === label
      )
        return;
      const mod = MODULES.find((m) => m.slug === moduleSlug);
      if (!mod || !mod.sub) return;
      const ordered = applySubOrder(mod.sub, subOrder[moduleSlug]);
      const labels = ordered.map((s) => s.label);
      const from = labels.indexOf(draggingSub.label);
      const to = labels.indexOf(label);
      if (from < 0 || to < 0) return;
      const next = [...labels];
      next.splice(from, 1);
      next.splice(to, 0, draggingSub.label);
      const newSubOrder = { ...subOrder, [moduleSlug]: next };
      setSubOrder(newSubOrder);
      writeSubOrder(newSubOrder);
      setDraggingSub(null);
    };
  }

  function handleSubDragEnd() {
    setDraggingSub(null);
  }

  function resetOrder() {
    setOrder(null);
    setSubOrder({});
    try {
      localStorage.removeItem(ORDER_KEY);
      localStorage.removeItem(SUBORDER_KEY);
    } catch {
      /* */
    }
  }

  return (
    <aside className={clsx(layoutWidth, "relative shrink-0 transition-[width] duration-150")}>
      <div
        className={clsx(
          "absolute inset-y-0 left-0 z-30 flex flex-col border-r border-line bg-surface transition-[width] duration-150",
          contentWidth,
          collapsed && hoverExpanded && "shadow-pop",
        )}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
      >
        {/* лого (редактируемое) + collapse-тоггл */}
        <div className={clsx("flex items-center gap-2 px-3 py-4", showFull && "px-5")}>
          <span
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-white"
            title={!showFull ? logoText : undefined}
          >
            <Box size={20} />
          </span>
          {showFull && !logoEditing && (
            <button
              type="button"
              onClick={() => {
                setLogoDraft(logoText);
                setLogoEditing(true);
              }}
              title="Клик — переименовать"
              className="min-w-0 flex-1 truncate rounded px-1 text-left text-lg font-bold text-ink hover:bg-sunken"
            >
              {logoText}
            </button>
          )}
          {showFull && logoEditing && (
            <input
              autoFocus
              value={logoDraft}
              onChange={(e) => setLogoDraft(e.target.value)}
              onBlur={commitLogo}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitLogo();
                if (e.key === "Escape") cancelLogo();
              }}
              maxLength={24}
              className="min-w-0 flex-1 rounded border border-accent bg-surface px-1 text-lg font-bold text-ink outline-none"
            />
          )}
          {showFull && (
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Раскрыть меню" : "Свернуть меню"}
              title={collapsed ? "Раскрыть меню" : "Свернуть меню"}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          )}
        </div>

        <nav className="thin-scroll flex-1 overflow-y-auto overflow-x-hidden px-3 pb-4">
          {showFull && (
            <div className="flex items-center justify-between px-3 pb-2 pt-3">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Модули
              </span>
              <div className="flex items-center gap-1">
                {editing && (order || Object.keys(subOrder).length > 0) && (
                  <button
                    type="button"
                    onClick={resetOrder}
                    title="Вернуть исходный порядок (модули + подразделы)"
                    className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold text-faint hover:bg-sunken hover:text-ink"
                  >
                    сброс
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setEditing((v) => !v)}
                  aria-label={editing ? "Готово" : "Редактировать меню"}
                  title={
                    editing
                      ? "Готово — выйти из режима правки"
                      : "Редактировать меню (перетаскивание модулей и подразделов)"
                  }
                  className={clsx(
                    "flex h-6 w-6 items-center justify-center rounded-md",
                    editing
                      ? "bg-accent-soft text-accent-ink"
                      : "text-faint hover:bg-sunken hover:text-ink",
                  )}
                >
                  <Pencil size={12} />
                </button>
              </div>
            </div>
          )}

          {visibleModules.map((m) => {
            const active = moduleActive(m);
            const isDragSrc = draggingSlug === m.slug;
            const rowCls = clsx(
              "group relative flex items-center gap-3 rounded-lg text-sm font-medium transition-colors",
              showFull ? "px-3 py-2" : "h-10 justify-center",
              active ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-sunken",
              editing && showFull && "cursor-grab active:cursor-grabbing",
              isDragSrc && "opacity-40",
            );
            const rowBody = (
              <>
                {editing && showFull && (
                  <GripVertical size={14} className="-ml-1 shrink-0 text-faint" aria-hidden />
                )}
                <m.Icon size={18} />
                {showFull && <span className="truncate">{m.label}</span>}
              </>
            );
            return (
              <div
                key={m.slug}
                draggable={editing && showFull}
                onDragStart={handleDragStart(m.slug)}
                onDragOver={handleDragOver(m.slug)}
                onDrop={handleDrop(m.slug)}
                onDragEnd={handleDragEnd}
              >
                {m.href && !editing ? (
                  <Link href={m.href} className={rowCls} title={!showFull ? m.label : undefined}>
                    {rowBody}
                  </Link>
                ) : (
                  <div
                    className={clsx(rowCls, !editing && "cursor-default")}
                    title={
                      !showFull
                        ? m.label
                        : editing
                          ? "Перетащите для смены порядка"
                          : "Модуль"
                    }
                  >
                    {rowBody}
                  </div>
                )}
                {/* Подменю активного модуля — в раскрытом виде. В edit-mode подразделы
                    тоже становятся draggable (см. handleSubDrag*). */}
                {showFull && m.sub && active && (
                  <div className="mb-1 mt-1 flex flex-col">
                    {applySubOrder(m.sub, subOrder[m.slug]).map((s) => {
                      const sactive = !!s.href && pathname === s.href;
                      const isSubDragSrc =
                        draggingSub?.module === m.slug && draggingSub?.label === s.label;
                      const scls = clsx(
                        "flex items-center gap-2 rounded-lg py-1.5 pr-3 text-sm",
                        editing ? "pl-4" : "pl-11",
                        sactive
                          ? "font-medium text-accent-ink"
                          : "text-muted hover:bg-sunken",
                        editing && "cursor-grab active:cursor-grabbing",
                        isSubDragSrc && "opacity-40",
                      );
                      const subBody = (
                        <>
                          {editing && (
                            <GripVertical
                              size={12}
                              className="shrink-0 text-faint"
                              aria-hidden
                            />
                          )}
                          <span className="truncate">{s.label}</span>
                        </>
                      );
                      return (
                        <div
                          key={s.label}
                          draggable={editing}
                          onDragStart={handleSubDragStart(m.slug, s.label)}
                          onDragOver={handleSubDragOver(m.slug, s.label)}
                          onDrop={handleSubDrop(m.slug, s.label)}
                          onDragEnd={handleSubDragEnd}
                        >
                          {s.href && !editing ? (
                            <Link href={s.href} className={scls}>
                              {subBody}
                            </Link>
                          ) : (
                            <div
                              className={clsx(scls, !editing && "cursor-default")}
                              title={
                                editing
                                  ? "Перетащите для смены порядка"
                                  : s.href
                                    ? undefined
                                    : "Раздел в разработке"
                              }
                            >
                              {subBody}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

          {/* В свёрнутом виде показываем мини-тоггл для раскрытия (для тач-устройств без hover). */}
          {!showFull && (
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label="Раскрыть меню"
              title="Раскрыть меню"
              className="mt-2 flex h-10 w-full items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
            >
              <PanelLeftOpen size={16} />
            </button>
          )}
        </nav>

        {/* профиль вошедшего сотрудника + выход (dev-логин; реальный — Keycloak, часть 5) */}
        {userName && (
          <div
            className={clsx(
              "flex items-center border-t border-line",
              showFull ? "gap-3 px-4 py-3" : "justify-center px-2 py-3",
            )}
          >
            <span
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-xs font-semibold text-white"
              title={!showFull ? userName : undefined}
            >
              {initials(userName)}
            </span>
            {showFull && (
              <>
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="truncate text-sm font-medium text-ink">{userName}</div>
                  <div className="truncate text-xs text-muted">{roleTitle ?? "—"}</div>
                </div>
                <button
                  type="button"
                  onClick={logout}
                  aria-label="Выйти"
                  title="Выйти"
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
                >
                  <LogOut size={16} />
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
