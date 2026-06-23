"use client";

import {
  AlertTriangle,
  Building2,
  ClipboardCheck,
  Eye,
  FileBarChart,
  FileSignature,
  FileText,
  Files,
  Folder,
  FolderOpen,
  Lock,
  Pencil,
  Receipt,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Snowflake,
  Trash2,
  Truck,
  Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatByn } from "@/lib/format";

// demo-данные (бэкенда по экрану пока нет). Валюта — BYN.
// Реестр — проекция, а не второе хранилище: документ принадлежит сделке → менеджеру → отделу.
// Видимость задаётся ролью; «врезка в отдел» — тот же реестр с фильтром по отделу.

type IconCmp = React.ComponentType<{ size?: number; className?: string }>;

type Kind = "Счёт" | "Договор" | "КП" | "Акт" | "Заказ-наряд" | "Накладная";

type StatusKey = "posted" | "pending" | "paid" | "draft" | "signed";

type RoleKey = "manager" | "rop" | "director";

type GroupKey = "dept" | "client" | "kind" | "deal" | "flat";

type Doc = {
  n: string;
  kind: Kind;
  mgr: string;
  dept: string;
  deal: string;
  client: string;
  st: StatusKey;
  lbl: string;
  ver: number;
  signed: boolean;
  paid: boolean;
  date: string; // дд.мм.гггг
  amount: number;
  del?: boolean;
  reason?: string;
};

// отделы и принадлежность менеджеров
const MGR_DEPT: Record<string, string> = {
  "Сидоров К.": "Отдел продаж · Новые",
  "Петрова А.": "Отдел продаж · Новые",
  "Иванов И.": "Отдел продаж · Постоянные",
  "Ковалёва М.": "Отдел продаж · Постоянные",
  "Морозов Д.": "Тендерный отдел",
};

const DEPT_ICON: Record<string, IconCmp> = {
  "Отдел продаж · Новые": Folder,
  "Отдел продаж · Постоянные": RotateCcw,
  "Тендерный отдел": FileBarChart,
};

const KIND_ICON: Record<Kind, IconCmp> = {
  "Счёт": Receipt,
  "Договор": FileSignature,
  "КП": FileBarChart,
  "Акт": ClipboardCheck,
  "Заказ-наряд": Wrench,
  "Накладная": Truck,
};

const STATUS_CLS: Record<StatusKey, string> = {
  posted: "bg-emerald-50 text-emerald-600",
  pending: "bg-amber-50 text-amber-600",
  paid: "bg-blue-50 text-blue-600",
  draft: "bg-sunken text-muted",
  signed: "bg-violet-50 text-violet-600",
};

// роли → область видимости
const ROLES: Record<
  RoleKey,
  { label: string; scope: string; filter: (d: Doc) => boolean }
> = {
  manager: {
    label: "Менеджер (Сидоров К.)",
    scope: "свои сделки",
    filter: (d) => d.mgr === "Сидоров К.",
  },
  rop: {
    label: "РОП (Новые)",
    scope: "отдел «Отдел продаж · Новые»",
    filter: (d) => d.dept === "Отдел продаж · Новые",
  },
  director: {
    label: "Директор / Архивариус",
    scope: "все отделы",
    filter: () => true,
  },
};

const ROLE_ICON: Record<RoleKey, IconCmp> = {
  manager: FileText,
  rop: ShieldCheck,
  director: Building2,
};

const GROUP_OPTIONS: { key: GroupKey; label: string }[] = [
  { key: "dept", label: "по отделу" },
  { key: "client", label: "по контрагенту" },
  { key: "kind", label: "по типу" },
  { key: "deal", label: "по сделке" },
  { key: "flat", label: "плоско" },
];

const RAW_DOCS: Omit<Doc, "dept">[] = [
  { n: "Счёт СЧ-0461", kind: "Счёт", mgr: "Сидоров К.", deal: "CRM-1024 · Автопарк №7", client: "Автопарк №7", st: "posted", lbl: "отправлен", ver: 1, signed: false, paid: false, date: "14.06.2026", amount: 12_400 },
  { n: "Договор ДГ-0118", kind: "Договор", mgr: "Сидоров К.", deal: "CRM-1029 · ОАО «Белтранс»", client: "Белтранс", st: "signed", lbl: "подписан", ver: 2, signed: true, paid: false, date: "12.06.2026", amount: 86_000 },
  { n: "Счёт СЧ-0420", kind: "Счёт", mgr: "Сидоров К.", deal: "CRM-1029 · ОАО «Белтранс»", client: "Белтранс", st: "paid", lbl: "оплачен", ver: 1, signed: false, paid: true, date: "10.06.2026", amount: 86_000 },
  { n: "КП-0288", kind: "КП", mgr: "Петрова А.", deal: "CRM-1024 · Автопарк №7", client: "Автопарк №7", st: "posted", lbl: "просмотрен", ver: 1, signed: false, paid: false, date: "13.06.2026", amount: 45_000, del: true, reason: "устаревшие цены" },
  { n: "Заказ-наряд ЗН-0207", kind: "Заказ-наряд", mgr: "Петрова А.", deal: "CRM-1031 · СТО «Вираж»", client: "СТО Вираж", st: "pending", lbl: "в работе", ver: 1, signed: false, paid: false, date: "11.06.2026", amount: 7_200 },
  { n: "Счёт СЧ-0455", kind: "Счёт", mgr: "Иванов И.", deal: "CRM-1031 · СТО «Вираж»", client: "СТО Вираж", st: "paid", lbl: "оплачен", ver: 2, signed: false, paid: true, date: "11.06.2026", amount: 31_000 },
  { n: "Акт АКТ-0140", kind: "Акт", mgr: "Иванов И.", deal: "CRM-1015 · ООО «Логист»", client: "Логист", st: "posted", lbl: "подписан", ver: 1, signed: true, paid: false, date: "09.06.2026", amount: 19_800 },
  { n: "Договор ДГ-0120", kind: "Договор", mgr: "Морозов Д.", deal: "CRM-1040 · РУП «Белэнерго»", client: "Белэнерго", st: "signed", lbl: "подписан", ver: 1, signed: true, paid: false, date: "10.06.2026", amount: 240_000 },
  { n: "КП-0301", kind: "КП", mgr: "Морозов Д.", deal: "CRM-1041 · РУП «Минскэнерго»", client: "Минскэнерго", st: "draft", lbl: "черновик", ver: 1, signed: false, paid: false, date: "14.06.2026", amount: 180_000 },
  { n: "ТТН-0512", kind: "Накладная", mgr: "Ковалёва М.", deal: "CRM-1033 · ИП Сергеев", client: "ИП Сергеев", st: "draft", lbl: "черновик", ver: 1, signed: false, paid: false, date: "15.06.2026", amount: 4_100 },
];

const INITIAL_DOCS: Doc[] = RAW_DOCS.map((d) => ({
  ...d,
  dept: MGR_DEPT[d.mgr] ?? "Без отдела",
}));

// дата "дд.мм.гггг" → "гггг-мм-дд" (для сравнения с <input type=date>)
function isoOf(ddmmyyyy: string): string {
  const [d, m, y] = ddmmyyyy.split(".");
  return `${y}-${m}-${d}`;
}

// быстрый период: последние N дней от 15.06.2026 (демо-«сегодня»)
function quickRange(days: number): { from: string; to: string } {
  const today = new Date(2026, 5, 15);
  const past = new Date(today);
  past.setDate(today.getDate() - days + 1);
  const iso = (dt: Date) =>
    `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
  return { from: iso(past), to: iso(today) };
}

const EMPTY_FILTERS = {
  client: "",
  dept: "",
  mgr: "",
  kind: "",
  status: "",
  from: "",
  to: "",
  q: "",
  delOnly: false,
};

type Filters = typeof EMPTY_FILTERS;

const SELECT_CLS =
  "rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-muted focus:border-accent focus:outline-none";

const CHIP_CLS =
  "rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-semibold text-muted hover:border-accent hover:bg-accent-soft hover:text-accent-ink";

export function DocsRegistry() {
  const [docs, setDocs] = useState<Doc[]>(INITIAL_DOCS);
  const [role, setRole] = useState<RoleKey>("manager");
  const [group, setGroup] = useState<GroupKey>("dept");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [toast, setToast] = useState<string | null>(null);

  function notify(msg: string) {
    setToast(msg);
  }

  function patchFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  // документы, видимые роли (до фильтров) — для опций селектов
  const visible = useMemo(() => docs.filter(ROLES[role].filter), [docs, role]);

  const options = useMemo(() => {
    const uniq = (arr: string[]) => [...new Set(arr)].sort();
    return {
      client: uniq(visible.map((d) => d.client)),
      dept: uniq(visible.map((d) => d.dept)),
      mgr: uniq(visible.map((d) => d.mgr)),
      kind: uniq(visible.map((d) => d.kind)),
      status: uniq(visible.map((d) => d.lbl)),
    };
  }, [visible]);

  const filtered = useMemo(() => {
    const q = filters.q.toLowerCase();
    return visible.filter((d) => {
      const iso = isoOf(d.date);
      return (
        (!filters.client || d.client === filters.client) &&
        (!filters.dept || d.dept === filters.dept) &&
        (!filters.mgr || d.mgr === filters.mgr) &&
        (!filters.kind || d.kind === filters.kind) &&
        (!filters.status || d.lbl === filters.status) &&
        (!filters.delOnly || d.del) &&
        (!filters.from || iso >= filters.from) &&
        (!filters.to || iso <= filters.to) &&
        (!q || `${d.n} ${d.deal} ${d.client}`.toLowerCase().includes(q))
      );
    });
  }, [visible, filters]);

  // скорборд
  const stats = useMemo(() => {
    const sum = filtered.reduce((s, d) => s + d.amount, 0);
    const del = filtered.filter((d) => d.del).length;
    const frozen = filtered.filter((d) => d.signed || d.paid).length;
    return { count: filtered.length, sum, del, frozen };
  }, [filtered]);

  // группировка
  const groups = useMemo(() => {
    if (group === "flat") {
      const gsum = filtered.reduce((s, d) => s + d.amount, 0);
      return filtered.length
        ? [{ key: "__flat", title: "Все документы", icon: Files, items: filtered, sum: gsum }]
        : [];
    }
    const keyOf: Record<Exclude<GroupKey, "flat">, (d: Doc) => string> = {
      dept: (d) => d.dept,
      client: (d) => d.client,
      kind: (d) => d.kind,
      deal: (d) => d.deal,
    };
    const iconOf = (k: string): IconCmp => {
      if (group === "dept") return DEPT_ICON[k] ?? FolderOpen;
      if (group === "client") return Building2;
      if (group === "kind") return KIND_ICON[k as Kind] ?? FileText;
      return Files;
    };
    const buckets = new Map<string, Doc[]>();
    for (const d of filtered) {
      const k = keyOf[group](d);
      const arr = buckets.get(k) ?? [];
      arr.push(d);
      buckets.set(k, arr);
    }
    return [...buckets.keys()]
      .sort()
      .map((k) => {
        const items = buckets.get(k) ?? [];
        return {
          key: k,
          title: k,
          icon: iconOf(k),
          items,
          sum: items.reduce((s, d) => s + d.amount, 0),
        };
      });
  }, [filtered, group]);

  function changeRole(r: RoleKey) {
    setRole(r);
    // сбросить фильтры под новую видимость (как в макете)
    setFilters((f) => ({ ...f, client: "", dept: "", mgr: "", kind: "", status: "" }));
  }

  function resetFilters() {
    setFilters(EMPTY_FILTERS);
  }

  function applyQuickDate(days: number) {
    if (!days) {
      setFilters((f) => ({ ...f, from: "", to: "" }));
      return;
    }
    const { from, to } = quickRange(days);
    setFilters((f) => ({ ...f, from, to }));
  }

  function markDoc(n: string) {
    setDocs((list) =>
      list.map((d) =>
        d.n === n ? { ...d, del: true, reason: d.reason ?? "помечено из реестра" } : d,
      ),
    );
    notify(`Помечен: ${n} — попадёт в Архив, отправка заблокирована`);
  }

  function unmarkDoc(n: string) {
    setDocs((list) => list.map((d) => (d.n === n ? { ...d, del: false } : d)));
    notify(`Пометка снята: ${n}`);
  }

  function reviseDoc(n: string) {
    let next = 0;
    setDocs((list) =>
      list.map((d) => {
        if (d.n !== n) return d;
        next = d.ver + 1;
        return { ...d, ver: next };
      }),
    );
    notify(`Новая версия v${next} · прежняя в истории сделки`);
  }

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
              <Files size={20} className="text-accent" /> Реестр документов
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-muted">
              Единый реестр всех документов сделок: счета, договоры, КП, акты, заказ-наряды,
              накладные. Видимость — по роли. Группировка переключается; «врезка в отдел» даёт
              тот же реестр с фильтром по отделу (без дублирования).
            </p>
          </div>
        </div>

        {/* Роль (демо-переключатель видимости) */}
        <div className="flex flex-wrap items-center gap-2.5 rounded-2xl border border-line bg-surface p-3 shadow-card">
          <span className="text-[12.5px] font-semibold text-muted">Я вошёл как:</span>
          <div className="inline-flex flex-wrap gap-1 rounded-xl bg-sunken p-1">
            {(Object.keys(ROLES) as RoleKey[]).map((r) => {
              const RoleIcon = ROLE_ICON[r];
              const on = role === r;
              return (
                <button
                  key={r}
                  onClick={() => changeRole(r)}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
                    on ? "bg-surface text-accent-ink shadow-card" : "text-muted hover:text-accent-ink"
                  }`}
                >
                  <RoleIcon size={14} /> {ROLES[r].label}
                </button>
              );
            })}
          </div>
          <span className="ml-auto text-xs text-muted">
            видит: <b className="text-ink">{ROLES[role].scope}</b>
          </span>
        </div>

        {/* Скорборд */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="text-xl font-bold tabular-nums text-ink">{stats.count}</div>
            <div className="mt-1 text-[11.5px] text-muted">документов видно</div>
          </div>
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="text-xl font-bold tabular-nums text-money">{formatByn(stats.sum)}</div>
            <div className="mt-1 text-[11.5px] text-muted">сумма по реестру</div>
          </div>
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-xl font-bold tabular-nums text-amber-600">
              <Snowflake size={16} /> {stats.frozen}
            </div>
            <div className="mt-1 text-[11.5px] text-muted">заморожено (подписан/оплачен)</div>
          </div>
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-xl font-bold tabular-nums text-red-600">
              <Trash2 size={16} /> {stats.del}
            </div>
            <div className="mt-1 text-[11.5px] text-muted">помечено на удаление</div>
          </div>
        </div>

        {/* Фильтры */}
        <div className="flex flex-wrap items-center gap-2.5 rounded-2xl border border-line bg-surface p-3 shadow-card">
          <label className="flex items-center gap-1.5 text-[11px] text-muted">
            Контрагент
            <select
              value={filters.client}
              onChange={(e) => patchFilter("client", e.target.value)}
              className={SELECT_CLS}
            >
              <option value="">Все контрагенты</option>
              {options.client.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-[11px] text-muted">
            Тип
            <select
              value={filters.kind}
              onChange={(e) => patchFilter("kind", e.target.value)}
              className={SELECT_CLS}
            >
              <option value="">Все типы</option>
              {options.kind.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-[11px] text-muted">
            Отдел
            <select
              value={filters.dept}
              onChange={(e) => patchFilter("dept", e.target.value)}
              className={SELECT_CLS}
            >
              <option value="">Все отделы</option>
              {options.dept.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-[11px] text-muted">
            Менеджер
            <select
              value={filters.mgr}
              onChange={(e) => patchFilter("mgr", e.target.value)}
              className={SELECT_CLS}
            >
              <option value="">Все менеджеры</option>
              {options.mgr.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-[11px] text-muted">
            Статус
            <select
              value={filters.status}
              onChange={(e) => patchFilter("status", e.target.value)}
              className={SELECT_CLS}
            >
              <option value="">Все статусы</option>
              {options.status.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>

          <span className="flex items-center gap-1.5 text-[11px] text-muted">
            Период
            <input
              type="date"
              value={filters.from}
              onChange={(e) => patchFilter("from", e.target.value)}
              title="дата с"
              className={SELECT_CLS}
            />
            <span className="text-muted">–</span>
            <input
              type="date"
              value={filters.to}
              onChange={(e) => patchFilter("to", e.target.value)}
              title="дата по"
              className={SELECT_CLS}
            />
          </span>

          <span className="flex gap-1">
            <button type="button" onClick={() => applyQuickDate(7)} className={CHIP_CLS}>
              7 дн
            </button>
            <button type="button" onClick={() => applyQuickDate(30)} className={CHIP_CLS}>
              30 дн
            </button>
            <button type="button" onClick={() => applyQuickDate(0)} className={CHIP_CLS}>
              сброс
            </button>
          </span>

          <label className="relative flex items-center">
            <Search size={14} className="pointer-events-none absolute left-2.5 text-faint" />
            <input
              type="search"
              value={filters.q}
              onChange={(e) => patchFilter("q", e.target.value)}
              placeholder="номер / сделка / клиент"
              className="rounded-lg border border-line bg-surface py-1.5 pl-8 pr-2.5 text-[12.5px] text-ink placeholder:text-faint focus:border-accent focus:outline-none"
            />
          </label>

          <label className="flex cursor-pointer select-none items-center gap-1.5 text-[12.5px] text-red-600">
            <input
              type="checkbox"
              checked={filters.delOnly}
              onChange={(e) => patchFilter("delOnly", e.target.checked)}
              className="accent-red-500"
            />
            <Trash2 size={13} /> только помеченные
          </label>

          <button
            type="button"
            onClick={resetFilters}
            title="Сбросить все фильтры"
            className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-[11.5px] font-semibold text-red-600 hover:bg-red-100"
          >
            Сбросить
          </button>

          <span className="ml-auto flex items-center gap-1.5">
            <SlidersHorizontalLabel />
            <select
              value={group}
              onChange={(e) => setGroup(e.target.value as GroupKey)}
              className={SELECT_CLS}
            >
              {GROUP_OPTIONS.map((g) => (
                <option key={g.key} value={g.key}>
                  {g.label}
                </option>
              ))}
            </select>
          </span>
        </div>

        {/* Примечание-проекция */}
        <div className="flex gap-2 rounded-xl border border-line bg-sunken p-3 text-[11.5px] leading-relaxed text-muted">
          <FileText size={15} className="mt-0.5 flex-shrink-0 text-faint" />
          <span>
            Реестр — <b className="font-semibold text-ink">проекция</b>, а не второе хранилище:
            документ принадлежит сделке → менеджеру → отделу; отдел здесь это фильтр через цепочку.
            Действия (правка/пометка) подчиняются тем же правилам, что в карточке: подписанный/
            оплаченный заморожен <Lock size={11} className="inline align-text-bottom" />, помеченный
            нельзя отправить, безвозвратно — в Архиве.
          </span>
        </div>

        {/* Список документов по группам */}
        {groups.length === 0 ? (
          <div className="rounded-2xl border border-line bg-surface p-10 text-center text-sm text-faint shadow-card">
            Нет документов под текущие фильтры/роль
          </div>
        ) : (
          groups.map((g) => {
            const GroupIcon = g.icon;
            return (
              <div
                key={g.key}
                className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card"
              >
                <div className="flex items-center gap-2.5 border-b border-line bg-sunken px-4 py-3">
                  <span className="flex items-center gap-2 text-sm font-semibold text-ink">
                    <GroupIcon size={15} className="text-muted" /> {g.title}
                  </span>
                  <span className="rounded-full bg-surface px-2.5 py-0.5 text-[11px] font-semibold text-muted">
                    {g.items.length}
                  </span>
                  <span className="ml-auto text-xs tabular-nums text-muted">{formatByn(g.sum)}</span>
                </div>

                {g.items.map((d) => (
                  <DocRow
                    key={d.n}
                    doc={d}
                    onPreview={() => notify(`Предпросмотр: ${d.n}`)}
                    onSend={() => notify(`Отправка: ${d.n}`)}
                    onSendBlocked={() => notify("Нельзя отправить — документ помечен на удаление")}
                    onRevise={() => reviseDoc(d.n)}
                    onFrozen={() =>
                      notify("Документ заморожен (подписан/оплачен) — правка и пометка запрещены")
                    }
                    onMark={() => markDoc(d.n)}
                    onUnmark={() => unmarkDoc(d.n)}
                  />
                ))}
              </div>
            );
          })
        )}
      </div>

      {toast && (
        <div className="fixed bottom-7 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-ink px-4 py-2.5 text-[13px] font-medium text-canvas shadow-pop">
          {toast}
        </div>
      )}
    </main>
  );
}

function SlidersHorizontalLabel() {
  return (
    <span className="flex items-center gap-1 text-[11px] text-muted">
      <SlidersHorizontal size={13} /> Группировать
    </span>
  );
}

function DocRow({
  doc,
  onPreview,
  onSend,
  onSendBlocked,
  onRevise,
  onFrozen,
  onMark,
  onUnmark,
}: {
  doc: Doc;
  onPreview: () => void;
  onSend: () => void;
  onSendBlocked: () => void;
  onRevise: () => void;
  onFrozen: () => void;
  onMark: () => void;
  onUnmark: () => void;
}) {
  const frozen = doc.signed || doc.paid;
  const KindIcon = KIND_ICON[doc.kind];
  const statusCls = doc.del ? "bg-red-50 text-red-600" : STATUS_CLS[doc.st];
  const statusLbl = doc.del ? "на удалении" : doc.lbl;

  return (
    <div
      className={`grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 border-b border-line px-4 py-3 last:border-0 ${
        doc.del ? "bg-red-50/40 opacity-70" : ""
      }`}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
          <span className={doc.del ? "line-through" : ""}>{doc.n}</span>
          <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-bold text-accent-ink">
            v{doc.ver}
          </span>
          {frozen && <Lock size={11} className="text-amber-600" />}
        </div>
        <div className="mt-0.5 truncate text-[11.5px] text-muted">
          <span className="font-semibold text-accent-ink">{doc.deal}</span> · {doc.mgr} · {doc.dept}{" "}
          · {doc.date} · <b className="tabular-nums text-ink">{formatByn(doc.amount)}</b>
          {doc.del && doc.reason ? ` · основание: ${doc.reason}` : ""}
        </div>
      </div>

      <span className="flex items-center gap-1.5 whitespace-nowrap rounded-md bg-sunken px-2 py-1 text-[11px] font-semibold text-muted">
        <KindIcon size={12} /> {doc.kind}
      </span>

      <span
        className={`whitespace-nowrap rounded-md px-2 py-0.5 text-[10px] font-bold ${statusCls}`}
      >
        {statusLbl}
      </span>

      <div className="flex gap-1.5">
        <IconBtn title="Просмотр" onClick={onPreview}>
          <Eye size={14} />
        </IconBtn>

        {doc.del ? (
          <IconBtn title="Помечен на удаление — отправка запрещена" disabled onClick={onSendBlocked}>
            <AlertTriangle size={14} />
          </IconBtn>
        ) : (
          <IconBtn title="Отправить" onClick={onSend}>
            <Send size={14} />
          </IconBtn>
        )}

        {frozen ? (
          <IconBtn title="Заморожен (юр. сила) — правка запрещена" disabled onClick={onFrozen}>
            <Lock size={14} />
          </IconBtn>
        ) : (
          <IconBtn title="Изменить (новая версия)" onClick={onRevise}>
            <Pencil size={14} />
          </IconBtn>
        )}

        {frozen ? (
          <IconBtn title="Заморожен — пометка запрещена" disabled onClick={onFrozen}>
            <Lock size={14} />
          </IconBtn>
        ) : doc.del ? (
          <IconBtn title="Снять пометку" onClick={onUnmark}>
            <RotateCcw size={14} />
          </IconBtn>
        ) : (
          <IconBtn title="Пометить на удаление" onClick={onMark}>
            <Trash2 size={14} />
          </IconBtn>
        )}
      </div>
    </div>
  );
}

function IconBtn({
  title,
  onClick,
  disabled,
  children,
}: {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={
        disabled
          ? "flex h-7 min-w-7 items-center justify-center rounded-lg border border-red-200 bg-red-50 px-2 text-red-600"
          : "flex h-7 min-w-7 items-center justify-center rounded-lg border border-line bg-surface px-2 text-muted hover:bg-sunken hover:text-accent-ink"
      }
    >
      {children}
    </button>
  );
}
