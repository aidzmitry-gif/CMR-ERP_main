"use client";

import Link from "next/link";
import { Archive, ChevronDown, ChevronRight, FolderPlus, GripVertical, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  archiveNomenclatureGroup,
  buildCategoryTree,
  createNomenclatureGroup,
  fetchRefRowsByEndpoint,
  fetchSkusByCategory,
  patchNomenclatureGroup,
  type CategoryTreeNode,
  type GroupDefaultFields,
  type NomenclatureGroup,
  type SkuRow,
} from "@/lib/reference-data";
import {
  buildBreadcrumb,
  filterFlatGroups,
  getDescendantIds,
  getNodeDepth,
} from "@/lib/spravochniki-categories";

// ── Типы модальных форм ─────────────────────────────────────────────────────

type Modal =
  | { kind: "add"; parentId: number | null; parentName: string | null }
  | { kind: "rename"; node: CategoryTreeNode }
  | { kind: "move"; node: CategoryTreeNode }
  | { kind: "defaults"; node: CategoryTreeNode }
  | { kind: "archive"; node: CategoryTreeNode }
  | null;

// ── Клиентский рефетч списка групп ─────────────────────────────────────────

async function refetchGroups(): Promise<NomenclatureGroup[]> {
  try {
    const res = await fetch("/api/system/refs/nomenclature-groups", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as NomenclatureGroup[];
  } catch {
    return [];
  }
}

// ── Компонент узла дерева (рекурсивный) ────────────────────────────────────

function TreeNodeRow({
  node,
  expanded,
  selectedId,
  search,
  onToggle,
  onSelect,
}: {
  node: CategoryTreeNode;
  expanded: Set<number>;
  selectedId: number | null;
  search: string;
  onToggle: (id: number) => void;
  onSelect: (node: CategoryTreeNode) => void;
}) {
  const isExpanded = expanded.has(node.id);
  const isSelected = node.id === selectedId;
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className={`flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors ${
          isSelected
            ? "bg-accent-soft text-accent-ink"
            : "text-ink hover:bg-sunken/60"
        }`}
        onClick={() => onSelect(node)}
      >
        <span
          className={`w-4 text-center ${isSelected ? "text-accent-ink/60" : "text-faint"}`}
          onClick={(e) => {
            e.stopPropagation();
            if (hasChildren) onToggle(node.id);
          }}
        >
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown size={14} />
            ) : (
              <ChevronRight size={14} />
            )
          ) : null}
        </span>
        <GripVertical
          size={14}
          className={isSelected ? "text-accent-ink/40" : "text-faint"}
        />
        <span
          className={`shrink-0 font-mono text-[11px] tabular-nums ${
            isSelected ? "text-accent-ink/70" : "text-faint"
          }`}
        >
          {node.code}
        </span>
        <span className={isSelected ? "font-semibold" : node.parent_id === null ? "font-medium" : ""}>
          {node.name}
        </span>
        {!node.is_active && (
          <span className="ml-1 rounded-full bg-sunken px-1.5 py-0.5 text-[10px] text-muted">
            архив
          </span>
        )}
      </div>

      {hasChildren && isExpanded && (
        <ul className="ml-5 space-y-0.5 border-l border-line pl-2">
          {node.children.map((child) => (
            <TreeNodeRow
              key={child.id}
              node={child}
              expanded={expanded}
              selectedId={selectedId}
              search={search}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

// ── Форма добавления группы ─────────────────────────────────────────────────

function AddForm({
  parentName,
  onSave,
  onCancel,
}: {
  parentName: string | null;
  onSave: (name: string, code: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !code.trim()) {
      setError("Заполните все поля");
      return;
    }
    setBusy(true);
    setError("");
    await onSave(name.trim(), code.trim().toUpperCase());
    setBusy(false);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {parentName && (
        <p className="text-sm text-muted">
          Родитель: <span className="font-medium text-ink">{parentName}</span>
        </p>
      )}
      <div>
        <label className="mb-1 block text-xs text-muted">Наименование</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Например: Конденсаторы"
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
        />
      </div>
      <div>
        <label className="mb-1 block text-xs text-muted">Код</label>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="CAT-0200"
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
        />
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="flex-1 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card disabled:opacity-50"
        >
          {busy ? "Сохранение…" : "Добавить"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}

// ── Форма переименования ─────────────────────────────────────────────────────

function RenameForm({
  node,
  onSave,
  onCancel,
}: {
  node: CategoryTreeNode;
  onSave: (name: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(node.name);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    await onSave(name.trim());
    setBusy(false);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label className="mb-1 block text-xs text-muted">Новое наименование</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
        />
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="flex-1 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card disabled:opacity-50"
        >
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}

// ── Форма переноса (смены родителя) ─────────────────────────────────────────

function MoveForm({
  node,
  groups,
  onSave,
  onCancel,
}: {
  node: CategoryTreeNode;
  groups: NomenclatureGroup[];
  onSave: (parentId: number | null) => Promise<void>;
  onCancel: () => void;
}) {
  const forbidden = useMemo(() => {
    const s = getDescendantIds(node.id, groups);
    s.add(node.id);
    return s;
  }, [node.id, groups]);

  const candidates = groups.filter((g) => !forbidden.has(g.id) && g.is_active);
  const [parentId, setParentId] = useState<number | null>(node.parent_id);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await onSave(parentId);
    setBusy(false);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label className="mb-1 block text-xs text-muted">Новый родитель</label>
        <select
          value={parentId ?? ""}
          onChange={(e) => setParentId(e.target.value === "" ? null : Number(e.target.value))}
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
        >
          <option value="">— корень —</option>
          {candidates.map((g) => (
            <option key={g.id} value={g.id}>
              {buildBreadcrumb(g.id, groups).join(" › ")}
            </option>
          ))}
        </select>
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="flex-1 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card disabled:opacity-50"
        >
          {busy ? "Перемещение…" : "Переместить"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}

// ── Форма «общих данных группы» (наследуются товарами) ──────────────────────

type RefRow = { code: string; title?: string };

// Свободные «общие данные группы» (наследуются товаром, JSONB category.attributes; миграция 0055).
// Ключи совпадают с backend _INHERITABLE_ATTR_KEYS / карточкой SKU (DEDICATED_ATTR_KEYS) — иначе
// наследование «↑ из группы» не подхватится. Бренд опускаем (синоним Марки), чтобы не плодить дубль.
const GROUP_ATTR_KEYS: { key: string; placeholder: string }[] = [
  { key: "Производитель", placeholder: "напр. Omron" },
  { key: "Марка", placeholder: "напр. G2R" },
  { key: "Импортёр", placeholder: "кто ввозит" },
  { key: "Кол-во в коробке", placeholder: "напр. 50" },
  { key: "Габариты", placeholder: "Д×Ш×В, мм" },
  { key: "Объём", placeholder: "напр. 0.5 л" },
];

/** Редактор полей по умолчанию группы: НДС/ед.изм/страна — select из справочников;
 *  ТН ВЭД — ввод кода (кодов много); свободные атрибуты (Производитель/коробка/габариты) —
 *  текст. Пустое значение = очистить (не наследовать). */
function GroupDefaultsForm({
  node,
  units,
  vats,
  countries,
  onSave,
  onCancel,
}: {
  node: CategoryTreeNode;
  units: RefRow[];
  vats: RefRow[];
  countries: RefRow[];
  onSave: (fields: GroupDefaultFields) => Promise<void>;
  onCancel: () => void;
}) {
  const [tnved, setTnved] = useState(node.tnved_code ?? "");
  const [vat, setVat] = useState(node.vat_code ?? "");
  const [unit, setUnit] = useState(node.unit ?? "");
  const [country, setCountry] = useState(node.country ?? "");
  // Свободные атрибуты группы — по известным ключам (значения из node.attributes как строки).
  const [attrs, setAttrs] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      GROUP_ATTR_KEYS.map(({ key }) => [key, String(node.attributes?.[key] ?? "")]),
    ),
  );
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    // attributes перезаписывается бэком целиком → стартуем с существующего словаря (сохраняя
    // неизвестные редактору ключи), known-ключи задаём/удаляем по введённому значению.
    const merged: Record<string, unknown> = { ...(node.attributes ?? {}) };
    for (const { key } of GROUP_ATTR_KEYS) {
      const v = attrs[key].trim();
      if (v) merged[key] = v;
      else delete merged[key];
    }
    await onSave({
      tnved_code: tnved.trim() || null,
      vat_code: vat || null,
      unit: unit || null,
      country: country || null,
      attributes: merged,
    });
    setBusy(false);
  }

  const sel =
    "w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20";

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <p className="text-[12px] text-muted">
        Значения по умолчанию для товаров группы — товар без своего наследует их (↑ из группы).
      </p>
      <div>
        <label className="mb-1 block text-xs text-muted">Код ТН ВЭД по умолч.</label>
        <input
          value={tnved}
          onChange={(e) => setTnved(e.target.value)}
          placeholder="напр. 8506108000 (пусто — наследовать)"
          className={`${sel} font-mono`}
        />
      </div>
      <div>
        <label className="mb-1 block text-xs text-muted">Ставка НДС по умолч.</label>
        <select value={vat} onChange={(e) => setVat(e.target.value)} className={sel}>
          <option value="">— не задано —</option>
          {vats.map((v) => (
            <option key={v.code} value={v.code}>
              {v.title ?? v.code}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-xs text-muted">
          Единица изм. — по умолч. для новых товаров
        </label>
        <select value={unit} onChange={(e) => setUnit(e.target.value)} className={sel}>
          <option value="">— не задано —</option>
          {units.map((u) => (
            <option key={u.code} value={u.code}>
              {u.title ?? u.code}
            </option>
          ))}
        </select>
        <p className="mt-1 text-[10.5px] text-faint">
          У товара ед.изм. задаётся всегда (по умолч. «шт») — это подсказка для НОВЫХ позиций группы,
          не перезапись существующих.
        </p>
      </div>
      <div>
        <label className="mb-1 block text-xs text-muted">Страна происхождения по умолч.</label>
        <select value={country} onChange={(e) => setCountry(e.target.value)} className={sel}>
          <option value="">— не задано —</option>
          {countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.title ?? c.code}
            </option>
          ))}
        </select>
      </div>

      {/* Свободные атрибуты группы (Производитель/коробка/габариты) — наследуются товаром */}
      <div className="border-t border-line pt-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
          Свободные характеристики
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {GROUP_ATTR_KEYS.map(({ key, placeholder }) => (
            <div key={key}>
              <label className="mb-1 block text-xs text-muted">{key}</label>
              <input
                value={attrs[key]}
                onChange={(e) => setAttrs((p) => ({ ...p, [key]: e.target.value }))}
                placeholder={placeholder}
                className={sel}
              />
            </div>
          ))}
        </div>
        <p className="mt-1 text-[10.5px] text-faint">
          Товар без своего значения наследует от группы (↑ из группы). Пусто — не наследовать.
        </p>
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="flex-1 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card disabled:opacity-50"
        >
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}

// ── Главный компонент ───────────────────────────────────────────────────────

export function SpravCategories({ initial }: { initial: NomenclatureGroup[] }) {
  const [groups, setGroups] = useState<NomenclatureGroup[]>(initial);
  const [selected, setSelected] = useState<CategoryTreeNode | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<Modal>(null);
  const [toast, setToast] = useState("");
  // Справочники для select'ов «общих данных группы» (тянем один раз клиентом).
  const [units, setUnits] = useState<RefRow[]>([]);
  const [vats, setVats] = useState<RefRow[]>([]);
  const [countries, setCountries] = useState<RefRow[]>([]);
  // Товары выбранной группы (членство по category_id) — read-only вид «что в категории».
  const [skus, setSkus] = useState<SkuRow[]>([]);
  const [skusLoading, setSkusLoading] = useState(false);

  useEffect(() => {
    (async () => {
      const [u, v, c] = await Promise.all([
        fetchRefRowsByEndpoint("/system/refs/units"),
        fetchRefRowsByEndpoint("/system/refs/vat-rates"),
        fetchRefRowsByEndpoint("/system/refs/countries"),
      ]);
      setUnits(u as RefRow[]);
      // НДС версионный — на код может быть несколько версий; берём по одной на код.
      const seen = new Set<string>();
      setVats(
        (v as RefRow[]).filter((r) => (seen.has(r.code) ? false : (seen.add(r.code), true))),
      );
      setCountries(c as RefRow[]);
    })();
  }, []);

  // Подгрузка товаров выбранной группы (членство по category_id). live-флаг гасит гонку.
  useEffect(() => {
    if (!selected) {
      setSkus([]);
      return;
    }
    let live = true;
    setSkusLoading(true);
    const id = selected.id;
    void fetchSkusByCategory(id).then((rows) => {
      if (live) {
        setSkus(rows);
        setSkusLoading(false);
      }
    });
    return () => {
      live = false;
    };
  }, [selected]);

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(""), 2500);
  }

  async function reload() {
    const fresh = await refetchGroups();
    setGroups(fresh);
    // обновить selected если он ещё существует
    if (selected) {
      const stillExists = fresh.find((g) => g.id === selected.id);
      if (!stillExists) setSelected(null);
    }
  }

  const filtered = useMemo(() => filterFlatGroups(groups, search), [groups, search]);
  const tree = useMemo(() => buildCategoryTree(filtered), [filtered]);

  // При активном поиске раскрываем весь отфильтрованный путь (иначе совпавшие дети
  // свёрнутых групп невидимы); без поиска — обычное ручное раскрытие.
  const effectiveExpanded = useMemo(
    () => (search.trim() ? new Set(filtered.map((g) => g.id)) : expanded),
    [search, filtered, expanded],
  );

  const toggleExpand = useCallback((id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  function handleSelect(node: CategoryTreeNode) {
    setSelected(node);
    setModal(null);
  }

  // CRUD handlers
  async function handleAdd(name: string, code: string) {
    const parentId = modal?.kind === "add" ? modal.parentId : null;
    const ok = await createNomenclatureGroup({ name, code, parent_id: parentId ?? undefined });
    if (ok) {
      await reload();
      setModal(null);
      flash("Группа добавлена");
    } else {
      flash("Ошибка: не удалось добавить группу");
    }
  }

  async function handleRename(name: string) {
    if (!selected) return;
    const ok = await patchNomenclatureGroup(selected.code, { name });
    if (ok) {
      await reload();
      setModal(null);
      flash("Переименовано");
    } else {
      flash("Ошибка: не удалось переименовать");
    }
  }

  async function handleMove(parentId: number | null) {
    if (!selected) return;
    const ok = await patchNomenclatureGroup(selected.code, { parent_id: parentId });
    if (ok) {
      await reload();
      setModal(null);
      flash("Перемещено");
    } else {
      flash("Ошибка: не удалось переместить");
    }
  }

  async function handleSaveDefaults(fields: GroupDefaultFields) {
    if (!selected) return;
    const ok = await patchNomenclatureGroup(selected.code, fields);
    if (ok) {
      await reload();
      setModal(null);
      flash("Общие данные группы сохранены");
    } else {
      flash("Ошибка: не удалось сохранить");
    }
  }

  async function handleArchive() {
    if (!selected) return;
    const ok = await archiveNomenclatureGroup(selected.code);
    if (ok) {
      setSelected(null);
      await reload();
      setModal(null);
      flash("Группа архивирована");
    } else {
      flash("Ошибка: не удалось архивировать");
    }
  }

  // Найти имя родителя для отображения в карточке
  const parentName = useMemo(() => {
    if (!selected?.parent_id) return null;
    return groups.find((g) => g.id === selected.parent_id)?.name ?? null;
  }, [selected, groups]);

  const depth = useMemo(
    () => (selected ? getNodeDepth(selected.id, groups) : null),
    [selected, groups],
  );

  return (
    <div className="mx-auto max-w-[1280px] space-y-4 p-6">
      {/* Тост */}
      {toast && (
        <div className="fixed right-6 top-6 z-50 rounded-xl bg-ink px-4 py-2 text-sm text-white shadow-card">
          {toast}
        </div>
      )}

      {/* Заголовок + поиск + добавить */}
      <div className="rounded-2xl bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-ink">Категории номенклатуры 🌳</h2>
            <span className="rounded-full bg-sunken px-2 py-0.5 font-mono text-[11px] text-muted">
              схема: public
            </span>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
              иерархия
            </span>
            <span className="rounded-full bg-sunken px-2 py-0.5 font-mono text-[11px] text-muted">
              parent_id
            </span>
            <Link
              href="/erp/spravochniki/sku"
              className="text-[12px] font-medium text-accent hover:underline"
            >
              📦 каталог SKU
            </Link>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-56 rounded-xl bg-sunken px-3 py-2">
              <input
                className="w-full bg-transparent text-ink text-sm outline-none placeholder:text-faint"
                placeholder="Поиск по дереву…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button
              onClick={() => setModal({ kind: "add", parentId: null, parentName: null })}
              className="flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card"
            >
              <Plus size={14} />
              Добавить категорию
            </button>
          </div>
        </div>
      </div>

      {/* Двухколоночный grid */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* ЛЕВО: дерево */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
            Дерево категорий
          </div>

          {tree.length === 0 ? (
            <p className="mt-6 text-center text-sm text-muted">
              {search ? "Ничего не найдено" : "Нет данных. Добавьте первую категорию."}
            </p>
          ) : (
            <div className="mt-3 max-h-[calc(100vh-320px)] overflow-y-auto pr-1">
              <ul className="space-y-0.5">
                {tree.map((node) => (
                  <TreeNodeRow
                    key={node.id}
                    node={node}
                    expanded={effectiveExpanded}
                    selectedId={selected?.id ?? null}
                    search={search}
                    onToggle={toggleExpand}
                    onSelect={handleSelect}
                  />
                ))}
              </ul>
            </div>
          )}

          <div className="mt-4 border-t border-line pt-3 text-[11px] text-faint">
            ▾ раскрыт · ▸ свёрнут · ⠿ перетащить для переноса
          </div>
        </div>

        {/* ПРАВО: карточка узла / форма */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          {modal?.kind === "add" ? (
            <>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Новая группа
              </div>
              <div className="mt-3">
                <AddForm
                  parentName={modal.parentName}
                  onSave={handleAdd}
                  onCancel={() => setModal(null)}
                />
              </div>
            </>
          ) : modal?.kind === "rename" && selected ? (
            <>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Переименовать
              </div>
              <div className="mt-3">
                <RenameForm
                  node={selected}
                  onSave={handleRename}
                  onCancel={() => setModal(null)}
                />
              </div>
            </>
          ) : modal?.kind === "move" && selected ? (
            <>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Переместить
              </div>
              <div className="mt-3">
                <MoveForm
                  node={selected}
                  groups={groups}
                  onSave={handleMove}
                  onCancel={() => setModal(null)}
                />
              </div>
            </>
          ) : modal?.kind === "defaults" && selected ? (
            <>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Общие данные группы
              </div>
              <div className="mt-3">
                <GroupDefaultsForm
                  node={selected}
                  units={units}
                  vats={vats}
                  countries={countries}
                  onSave={handleSaveDefaults}
                  onCancel={() => setModal(null)}
                />
              </div>
            </>
          ) : modal?.kind === "archive" && selected ? (
            <>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Архивировать
              </div>
              <div className="mt-4 space-y-3">
                <p className="text-sm text-ink">
                  Архивировать группу{" "}
                  <span className="font-semibold">{selected.name}</span>?
                </p>
                <p className="text-xs text-muted">
                  Группа будет скрыта из активных, но не удалена из базы.
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={handleArchive}
                    className="flex-1 rounded-xl bg-red-500 px-3 py-2 text-sm font-semibold text-white shadow-card"
                  >
                    Архивировать
                  </button>
                  <button
                    onClick={() => setModal(null)}
                    className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
                  >
                    Отмена
                  </button>
                </div>
              </div>
            </>
          ) : selected ? (
            <>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Узел
              </div>
              <div className="mt-2 flex items-center gap-2">
                <h3 className="text-base font-bold text-ink">{selected.name}</h3>
                {selected.is_active ? (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
                    Активна
                  </span>
                ) : (
                  <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
                    Архив
                  </span>
                )}
              </div>

              <dl className="mt-4 space-y-3 border-t border-line pt-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted">Код</dt>
                  <dd className="font-mono text-[13px] text-muted">{selected.code}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted">Наименование</dt>
                  <dd className="text-ink">{selected.name}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted">Родитель</dt>
                  <dd className="text-ink">{parentName ?? "—"}</dd>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <dt className="text-muted">Путь</dt>
                  <dd className="text-right font-mono text-[13px] text-muted">
                    {buildBreadcrumb(selected.id, groups).join(" › ")}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted">Уровень</dt>
                  <dd className="text-ink">{depth}</dd>
                </div>
              </dl>

              {/* Общие данные группы (наследуются товарами) */}
              <div className="mt-4 border-t border-line pt-4">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Общие данные группы
                  </p>
                  <button
                    onClick={() => setModal({ kind: "defaults", node: selected })}
                    className="text-[12px] font-medium text-accent hover:underline"
                  >
                    Изменить
                  </button>
                </div>
                <p className="mt-1 text-[11px] text-faint">
                  По умолчанию для товаров группы — наследуются (↑ из группы).
                </p>
                <dl className="mt-3 space-y-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted">ТН ВЭД</dt>
                    <dd className={selected.tnved_code ? "font-mono text-[13px] text-ink" : "text-faint"}>
                      {selected.tnved_code ?? "не задано"}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted">Ставка НДС</dt>
                    <dd className={selected.vat_code ? "text-ink" : "text-faint"}>
                      {selected.vat_code ?? "не задано"}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted">Ед. изм.</dt>
                    <dd className={selected.unit ? "text-ink" : "text-faint"}>
                      {selected.unit ?? "не задано"}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted">Страна</dt>
                    <dd className={selected.country ? "text-ink" : "text-faint"}>
                      {selected.country ?? "не задано"}
                    </dd>
                  </div>
                  {GROUP_ATTR_KEYS.filter(({ key }) => selected.attributes?.[key]).map(({ key }) => (
                    <div key={key} className="flex items-center justify-between gap-3">
                      <dt className="text-muted">{key}</dt>
                      <dd className="text-ink">{String(selected.attributes?.[key])}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              {/* Товары группы (членство по category_id) — read-only; привязка SKU→группа в карточке номенклатуры (CRM) */}
              <div className="mt-4 border-t border-line pt-4">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                    Товары группы
                  </p>
                  {!skusLoading && (
                    <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
                      {skus.length}
                      {skus.length === 50 ? "+" : ""}
                    </span>
                  )}
                </div>
                {skusLoading ? (
                  <p className="mt-2 text-[12px] text-faint">Загрузка…</p>
                ) : skus.length === 0 ? (
                  <p className="mt-2 text-[12px] text-faint">
                    Нет товаров в этой группе. Привязка товара к группе — в карточке номенклатуры.
                  </p>
                ) : (
                  <ul className="mt-2 max-h-44 space-y-1 overflow-y-auto pr-1">
                    {skus.map((s) => (
                      <li key={s.code}>
                        <Link
                          href={`/erp/spravochniki/sku/${encodeURIComponent(s.code)}`}
                          className="flex items-center justify-between gap-2 rounded-lg px-1 py-0.5 text-[13px] hover:bg-sunken/60"
                        >
                          <span className="truncate text-ink" title={s.title}>
                            {s.title}
                          </span>
                          <span className="shrink-0 font-mono text-[11px] text-faint">{s.code}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="mt-5 flex flex-col gap-2 border-t border-line pt-4">
                <button
                  onClick={() =>
                    setModal({
                      kind: "add",
                      parentId: selected.id,
                      parentName: selected.name,
                    })
                  }
                  className="flex items-center justify-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card"
                >
                  <FolderPlus size={14} />
                  Добавить подкатегорию
                </button>
                <div className="flex gap-2">
                  <button
                    onClick={() => setModal({ kind: "rename", node: selected })}
                    className="flex-1 rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
                  >
                    Переименовать
                  </button>
                  <button
                    onClick={() => setModal({ kind: "move", node: selected })}
                    className="flex-1 rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
                  >
                    Переместить…
                  </button>
                </div>
                {selected.is_active && (
                  <button
                    onClick={() => setModal({ kind: "archive", node: selected })}
                    className="flex items-center justify-center gap-1.5 rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line"
                  >
                    <Archive size={14} />В архив
                  </button>
                )}
              </div>
            </>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-muted">
              Выберите категорию в дереве
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
