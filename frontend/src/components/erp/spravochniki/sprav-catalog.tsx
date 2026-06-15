"use client";

import Link from "next/link";
import { Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import type { ReferenceCatalog, ReferenceMeta } from "@/lib/reference-data";
import { rowsSource, sortedDepartments } from "@/lib/spravochniki-catalog";

// Hub cards — shortcuts to the other 6 reference screens.
const HUB_LINKS = [
  {
    href: "/erp/spravochniki/counterparty",
    label: "Карточка контрагента",
    badge: "★",
    desc: "Golden record: реквизиты, алиасы-источники, аудит",
  },
  {
    href: "/erp/spravochniki/merge",
    label: "Дедупликация / слияние",
    badge: "",
    desc: "MDM: кандидаты-дубли, сравнение бок-о-бок, survivorship",
  },
  {
    href: "/erp/spravochniki/rates",
    label: "Версионный справочник",
    badge: "🕘",
    desc: "Курсы валют по датам (SCD2): версии, предпросмотр на дату",
  },
  {
    href: "/erp/spravochniki/categories",
    label: "Иерархия категорий",
    badge: "🌳",
    desc: "Дерево номенклатуры: adjacency list, CRUD",
  },
  {
    href: "/erp/spravochniki/import",
    label: "Импорт из 1С",
    badge: "↧",
    desc: "Входной адаптер: маппинг, конфликты, синхронизация",
  },
  {
    href: "/erp/spravochniki/ai",
    label: "Доступ AI",
    badge: "🤖",
    desc: "Semantic layer + MCP-tool: структурный запрос к справочникам",
  },
] as const;

// Fetch rows client-side via Next.js API proxy (/api/* → backend).
// crud → GET по endpoint; query-list → reference.query по ключу;
// lookup-only → строк нет (см. rowsSource): данные у владельца, точечный доступ.
async function fetchRowsViaProxy(ref: ReferenceMeta): Promise<Record<string, unknown>[]> {
  const src = rowsSource(ref);
  if (src === "lookup-only") return [];
  try {
    if (src === "query-list") {
      const res = await fetch("/api/system/references/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref: ref.key, limit: 200 }),
      });
      if (!res.ok) return [];
      const data = (await res.json()) as { result?: unknown };
      return Array.isArray(data.result) ? (data.result as Record<string, unknown>[]) : [];
    }
    const res = await fetch(`/api${ref.endpoint}`);
    if (!res.ok) return [];
    const data: unknown = await res.json();
    return Array.isArray(data) ? (data as Record<string, unknown>[]) : [];
  } catch {
    return [];
  }
}

interface SearchBoxProps {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}

function SearchBox({ value, onChange, placeholder }: SearchBoxProps) {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2">
      <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
      <input
        className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

interface Props {
  catalog: ReferenceCatalog;
  initialRef: ReferenceMeta | null;
  initialRows: Record<string, unknown>[];
}

export function SpravCatalog({ catalog, initialRef, initialRows }: Props) {
  const [selected, setSelected] = useState<ReferenceMeta | null>(initialRef);
  const [rows, setRows] = useState<Record<string, unknown>[]>(initialRows);
  const [loading, setLoading] = useState(false);
  const [treeSearch, setTreeSearch] = useState("");
  const [tableSearch, setTableSearch] = useState("");
  // Version counter prevents stale fetch responses from overwriting newer selections.
  const fetchVersion = useRef(0);

  async function selectRef(ref: ReferenceMeta) {
    if (ref.key === selected?.key) return;
    setSelected(ref);
    setTableSearch("");
    setLoading(true);
    const version = ++fetchVersion.current;
    const r = await fetchRowsViaProxy(ref);
    if (fetchVersion.current !== version) return;
    setRows(r);
    setLoading(false);
  }

  // catalog is a static SSR prop — memoize the sort to avoid re-sorting on every keystroke.
  const groups = useMemo(() => sortedDepartments(catalog), [catalog]);

  const treeQ = treeSearch.trim().toLowerCase();
  const filteredGroups = treeQ
    ? groups
        .map((g) => ({
          ...g,
          refs: g.refs.filter((r) => r.title.toLowerCase().includes(treeQ)),
        }))
        .filter((g) => g.refs.length > 0)
    : groups;

  const tableQ = tableSearch.trim().toLowerCase();
  const visibleRows = tableQ
    ? rows.filter((row) =>
        Object.values(row).some((v) => String(v ?? "").toLowerCase().includes(tableQ)),
      )
    : rows;

  return (
    <div className="space-y-4">
      {/* Info banner — registry pattern explanation */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-2xl bg-brand-100/60 px-4 py-2.5 text-[12px] text-slate-600">
        <span className="font-semibold text-brand-600">Как это устроено:</span>
        <span>
          📇 это <b>реестр-витрина</b>, а не второе хранилище
        </span>
        <span>
          🔒 у каждого справочника — <b>владелец</b>
        </span>
        <span>🗃 архив вместо удаления</span>
        <span>
          🕘 у части — <b>история по датам</b>
        </span>
        <span>🤖 точный доступ для AI</span>
      </div>

      {/* Hub — links to the other 6 screens */}
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
        {HUB_LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="rounded-2xl bg-white p-3 shadow-card ring-1 ring-slate-100 transition-shadow hover:ring-2 hover:ring-brand/40"
          >
            <div className="text-sm font-semibold text-ink">
              {link.badge && (
                <span className="mr-1 text-brand-600">{link.badge}</span>
              )}
              {link.label}
            </div>
            <div className="mt-0.5 text-[12px] text-muted">{link.desc}</div>
          </Link>
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
        <span>Значки:</span>
        <span>★ мастер-данные (golden record)</span>
        <span>🕘 версионный (история по датам)</span>
        <span>🌳 иерархия (дерево)</span>
        <span>🤖 в каталоге для AI</span>
      </div>

      {/* 2-col layout: left tree + right table */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
        {/* Left: department tree */}
        <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
          {/* Tree search */}
          <div className="rounded-2xl bg-white p-2 shadow-card">
            <SearchBox
              value={treeSearch}
              onChange={setTreeSearch}
              placeholder="Найти справочник…"
            />
          </div>

          {/* Nav tree */}
          <nav className="max-h-[calc(100vh-12rem)] overflow-y-auto rounded-2xl bg-white p-2 shadow-card text-[13px]">
            {groups.length === 0 ? (
              <div className="px-2 py-6 text-center text-sm text-muted">
                Каталог недоступен
              </div>
            ) : filteredGroups.length === 0 ? (
              <div className="px-2 py-6 text-center text-sm text-muted">
                Ничего не найдено
              </div>
            ) : (
              filteredGroups.map((group) => (
                <div key={group.dept}>
                  <div className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    {group.icon} {group.dept}
                  </div>
                  <ul className="mb-1">
                    {group.refs.map((ref) => {
                      const isActive = selected?.key === ref.key;
                      return (
                        <li key={ref.key}>
                          <button
                            type="button"
                            onClick={() => void selectRef(ref)}
                            className={`flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left transition-colors ${
                              isActive
                                ? "bg-brand-100 font-semibold text-brand-600"
                                : "hover:bg-slate-50"
                            }`}
                          >
                            <span>{ref.title}</span>
                            <span className="flex shrink-0 gap-0.5">
                              {ref.versioned && (
                                <span title="версионный">🕘</span>
                              )}
                              {ref.ai_exposed && (
                                <span title="в каталоге AI">🤖</span>
                              )}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </nav>
        </aside>

        {/* Right: reference table */}
        <section>
          {selected ? (
            <div className="rounded-2xl bg-white shadow-card">
              {/* Ref header */}
              <div className="border-b border-slate-100 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-bold text-ink">
                      {selected.title}
                      {selected.versioned && (
                        <span className="ml-2 text-base">🕘</span>
                      )}
                      {selected.ai_exposed && (
                        <span className="ml-2 text-base">🤖</span>
                      )}
                    </h2>
                    <p className="mt-0.5 text-sm text-muted">
                      {selected.description || `Владелец — ${selected.module}`}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
                      схема: {selected.owner_schema}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-slate-600">
                      {selected.endpoint}
                    </span>
                    {selected.ai_exposed && (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-semibold text-emerald-700">
                        🤖 в каталоге AI
                      </span>
                    )}
                    {selected.permissions.length > 0 && (
                      <span className="rounded-full bg-blue-50 px-2 py-0.5 font-semibold text-blue-700">
                        права: {selected.permissions.join(" · ")}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Table toolbar */}
              <div className="flex flex-wrap items-center gap-2 px-5 py-3">
                <div className="min-w-[220px] flex-1">
                  <SearchBox
                    value={tableSearch}
                    onChange={setTableSearch}
                    placeholder="Поиск по таблице…"
                  />
                </div>
              </div>

              {/* Table */}
              {loading ? (
                <div className="px-5 py-8 text-center text-sm text-muted">
                  Загрузка…
                </div>
              ) : rowsSource(selected) === "lookup-only" ? (
                <div className="rounded-xl bg-slate-50 px-5 py-8 text-center text-sm text-muted">
                  Данные у владельца — список не выгружается целиком.
                  <br />
                  Точечный доступ: карточка эталона, дедупликация или структурный запрос AI
                  (<span className="font-mono text-[12px]">reference.query</span> по УНП / имени).
                </div>
              ) : selected.columns.length === 0 ? (
                <div className="px-5 py-8 text-center text-sm text-muted">
                  Структура колонок недоступна
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-y border-slate-100 bg-slate-50/60 text-left text-[11px] uppercase tracking-wide text-slate-400">
                        {selected.columns.map((col) => (
                          <th
                            key={col.name}
                            className="px-4 py-2 font-semibold"
                          >
                            {col.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-50">
                      {visibleRows.length === 0 ? (
                        <tr>
                          <td
                            colSpan={selected.columns.length}
                            className="px-4 py-6 text-center text-muted"
                          >
                            {tableSearch ? "Ничего не найдено" : "Нет данных"}
                          </td>
                        </tr>
                      ) : (
                        visibleRows.map((row, i) => (
                          <tr
                            key={String(row.id ?? row.code ?? i)}
                            className={`hover:bg-slate-50/60 ${!row.is_active && row.is_active != null ? "opacity-50" : ""}`}
                          >
                            {selected.columns.map((col) => {
                              const val = row[col.name];
                              if (col.name === "is_active") {
                                return (
                                  <td key={col.name} className="px-4 py-2.5">
                                    {!val && val != null ? (
                                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
                                        Архив
                                      </span>
                                    ) : (
                                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                                        Активен
                                      </span>
                                    )}
                                  </td>
                                );
                              }
                              return (
                                <td key={col.name} className="px-4 py-2.5 text-ink">
                                  {val != null ? (
                                    String(val)
                                  ) : (
                                    <span className="text-slate-300">—</span>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Footer */}
              {selected.archivable && (
                <div className="border-t border-slate-100 px-5 py-3 text-[12px] text-muted">
                  Записи архивируются, не удаляются — на них могут ссылаться документы.
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-2xl bg-white p-8 text-center shadow-card">
              <p className="text-sm text-muted">Выберите справочник в дереве слева</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
