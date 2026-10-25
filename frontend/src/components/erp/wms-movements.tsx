"use client";

import clsx from "clsx";
import { ArrowLeftRight, ArrowUpFromLine, RefreshCw, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { InstanceOrganizationGate } from "@/components/instance-organization-gate";
import { fetchInstanceOrganization, type InstanceOrganization } from "@/lib/instance-organization";
import { formatNumber } from "@/lib/format";
import {
  adjustment,
  fetchMovements,
  fetchLocations,
  fetchOperationWarehouses,
  type OperationWarehousePage,
  locationLabel,
  REASON_LABELS,
  reasonLabel,
  shipment,
  type StockMovement,
  transfer,
  type WmsLocation,
} from "@/lib/wms-ops";

const KIND_BADGE: Record<string, string> = {
  receipt: "bg-green-100 text-green-700",
  shipment: "bg-red-100 text-red-700",
  transfer: "bg-blue-100 text-blue-700",
  adjustment: "bg-amber-100 text-amber-700",
  reserve: "bg-purple-100 text-purple-700",
  release: "bg-slate-100 text-slate-600",
  pick: "bg-orange-100 text-orange-700",
  pack: "bg-cyan-100 text-cyan-700",
};

function reasonBadge(reason: string) {
  return KIND_BADGE[reason] ?? "bg-sunken text-muted";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

// ponytail: client-side cap 50; add server-side cursor pagination when journal grows large
const PAGE_SIZE = 50;

function MovementsLog({ rows }: { rows: StockMovement[] }) {
  const [reasonFilter, setReasonFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const visible = useMemo(
    () =>
      rows
        .filter(
          (m) =>
            (!reasonFilter || m.reason === reasonFilter) &&
            (!dateFrom || (m.created_at && m.created_at >= dateFrom)) &&
            (!dateTo || (m.created_at && m.created_at <= dateTo + "T23:59:59")),
        )
        .slice(0, PAGE_SIZE),
    [rows, reasonFilter, dateFrom, dateTo],
  );

  return (
    <div className="mt-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select
          value={reasonFilter}
          onChange={(e) => setReasonFilter(e.target.value)}
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          <option value="">Все типы</option>
          {Object.entries(REASON_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
        />
        <span className="text-xs text-faint">—</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
        />
        {visible.length === PAGE_SIZE && (
          <span className="ml-auto text-xs text-faint">Показаны последние {PAGE_SIZE}</span>
        )}
      </div>
      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Юрлицо</th>
              <th className="px-4 py-2 font-medium">Дата</th>
              <th className="px-4 py-2 font-medium">Тип</th>
              <th className="px-4 py-2 font-medium">SKU</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
              <th className="px-4 py-2 font-medium">Документ</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  Движений по фильтру нет
                </td>
              </tr>
            )}
            {visible.map((m) => (
              <tr key={m.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-xs text-muted">{m.organization_id ? `Юрлицо №${m.organization_id}` : "Не определено"}</td>
                <td className="px-4 py-2.5 text-xs tabular-nums text-muted">
                  {formatDate(m.created_at)}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                      reasonBadge(m.reason),
                    )}
                  >
                    {reasonLabel(m.reason)}
                  </span>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{m.sku_code}</td>
                <td
                  className={clsx(
                    "px-4 py-2.5 text-right font-semibold tabular-nums",
                    m.kind === "in" ? "text-green-600" : "text-red-600",
                  )}
                >
                  {m.kind === "in" ? "+" : "−"}{formatNumber(m.qty)}
                </td>
                <td className="px-4 py-2.5 text-faint">{m.doc_ref || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type OpKind = "shipment" | "transfer" | "adjustment";

const OPS: { id: OpKind; label: string; Icon: typeof ArrowUpFromLine }[] = [
  { id: "shipment", label: "Отгрузка", Icon: ArrowUpFromLine },
  { id: "transfer", label: "Перемещение", Icon: ArrowLeftRight },
  { id: "adjustment", label: "Коррекция", Icon: SlidersHorizontal },
];

const EMPTY = { sku: "", qty: "", warehouse: "", loc: "", locTo: "", batch: "", note: "" };

export function WmsMovements() {
  return <InstanceOrganizationGate>{organization => <CompanyMovements key={organization.id} organization={organization} />}</InstanceOrganizationGate>;
}

function CompanyMovements({ organization }: { organization: InstanceOrganization }) {
  const [rows, setRows] = useState<StockMovement[] | null>(null);
  const [catalog, setCatalog] = useState<OperationWarehousePage | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [contextError, setContextError] = useState("");
  const [companyChanged, setCompanyChanged] = useState(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const [locationState, setLocationState] = useState<{ warehouse: string; rows: WmsLocation[]; error: string; loading: boolean }>({ warehouse: "", rows: [], error: "", loading: false });
  const [locationAttempt, setLocationAttempt] = useState(0);
  const [op, setOp] = useState<OpKind>("shipment");
  const [f, setF] = useState({ ...EMPTY });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const loadContext = useCallback(async (query: string) => {
    const request = ++generation.current;
    try {
      const [movements, warehouses] = await Promise.all([
        fetchMovements(organization.id), fetchOperationWarehouses(organization.id, query),
      ]);
      if (request !== generation.current) return false;
      setRows(movements);
      setCatalog(warehouses);
      setF(previous => warehouses.items.some(item => item.name === previous.warehouse)
        ? previous : { ...previous, warehouse: "", loc: "", locTo: "" });
      setContextError("");
      return true;
    } catch {
      if (request === generation.current) setContextError("Не удалось обновить журнал или склады. Показаны ранее загруженные движения, если они есть. Запись недоступна до успешной загрузки.");
      return false;
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [organization.id]);

  const invalidateRequests = useCallback(() => { generation.current++; }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- State updates follow the awaited remote reads.
    void loadContext("");
    mounted.current = true;
    return () => { mounted.current = false; invalidateRequests(); };
  }, [loadContext, invalidateRequests]);

  useEffect(() => {
    let active = true;
    if (f.warehouse) void fetchLocations(f.warehouse).then(rows => {
      if (active) setLocationState({ warehouse: f.warehouse, rows, loading: false, error: "" });
    }).catch(() => {
      if (active) setLocationState({ warehouse: f.warehouse, rows: [], loading: false,
        error: "Не удалось загрузить ячейки выбранного склада. Повторите загрузку перед записью." });
    });
    return () => { active = false; };
  }, [f.warehouse, locationAttempt]);

  const locationsLoading = !!f.warehouse && (locationState.warehouse !== f.warehouse || locationState.loading);
  const locationsError = locationState.warehouse === f.warehouse ? locationState.error : "";
  const locsForWh = locationState.warehouse === f.warehouse
    ? locationState.rows.filter(location => location.is_active && location.warehouse === f.warehouse) : [];

  function chooseWarehouse(name: string) {
    setF(previous => ({ ...previous, warehouse: name, loc: "", locTo: "" }));
    setLocationState({ warehouse: name, rows: [], error: "", loading: !!name });
  }

  async function refresh() {
    setLoading(true);
    if (await loadContext(search)) setMsg(null);
    setLocationState({ warehouse: f.warehouse, rows: [], error: "", loading: !!f.warehouse });
    setLocationAttempt(value => value + 1);
  }

  async function submit() {
    if (busy || loading || contextError || companyChanged || locationsLoading || locationsError) return;
    if (!catalog?.items.some(item => item.name === f.warehouse)) {
      setMsg({ ok: false, text: "Выберите склад операции" });
      return;
    }
    const quantity = f.qty.trim().replace(",", ".");
    if (!/^-?\d{1,12}(\.\d{1,2})?$/.test(quantity) || (op !== "adjustment" && quantity.startsWith("-"))) {
      setMsg({ ok: false, text: "Укажите корректное количество, не более двух знаков после запятой" });
      return;
    }
    const qty = Number(quantity);
    if (!f.sku.trim() || !qty) {
      setMsg({ ok: false, text: "Укажите SKU и количество" });
      return;
    }
    if ((f.loc && !locsForWh.some(location => String(location.id) === f.loc))
      || (op === "transfer" && (!f.loc || !f.locTo || f.loc === f.locTo
        || !locsForWh.some(location => String(location.id) === f.locTo)))) {
      setMsg({ ok: false, text: "Для перемещения выберите две разные ячейки выбранного склада" });
      return;
    }
    const request = generation.current;
    setBusy(true);
    const loc = f.loc ? Number(f.loc) : null;
    const base = { organization_id: organization.id, sku_code: f.sku.trim(), qty, warehouse: f.warehouse, batch_ref: f.batch.trim(), note: f.note.trim() };
    try {
      const current = await fetchInstanceOrganization();
      if (request !== generation.current) return;
      if (current.id !== organization.id || current.unp !== organization.unp) {
        setCompanyChanged(true);
        return;
      }
      let ok = false;
      if (op === "shipment") ok = await shipment({ ...base, location_id: loc });
      else if (op === "adjustment") ok = await adjustment({ ...base, location_id: loc });
      else ok = await transfer({ ...base, from_location_id: loc, to_location_id: f.locTo ? Number(f.locTo) : null });
      if (request !== generation.current) return;
      if (!ok) {
        setMsg({ ok: false, text: "Не удалось подтвердить запись. Обновите журнал перед повторной отправкой." });
        return;
      }
      setF({ ...EMPTY, warehouse: f.warehouse });
      setLoading(true);
      const loaded = await loadContext(search);
      if (!mounted.current) return;
      if (loaded) setMsg({ ok: true, text: "Движение записано" });
      else setMsg({ ok: false, text: "Движение записано, но журнал не обновился. Нажмите «Обновить»; повторно записывать операцию не нужно." });
    } catch {
      if (request === generation.current) setMsg({ ok: false, text: "Не удалось подтвердить запись. Обновите журнал перед повторной отправкой." });
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Складские операции записываются в <b>журнал движений ERP</b> с указанием юрлица.
          Физический остаток рассчитывается по этим движениям. Первичные накладные на поступление создаются в закупках,
          затем склад выполняет приёмку и QC по связанной накладной.
        </p>
        <div className="flex items-center gap-2">
          <Link href="/erp/wms/balances" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken">
            Остаток из движений →
          </Link>
          <Link href="/erp/procurement/receipts" className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink">
            Накладные на поступление →
          </Link>
          <button disabled={busy} onClick={refresh} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken">
            <RefreshCw size={15} /> Обновить
          </button>
        </div>
      </div>

      {companyChanged && <p role="alert" className="mt-3 text-red-700">Юрлицо установки изменилось. Перезагрузите страницу перед записью.</p>}
      {contextError && <p role="alert" className="mt-3 text-red-700">{contextError}</p>}
      {loading && <p role="status">Загрузка журнала и складов…</p>}
      {(catalog?.truncated || search) && <div className="mt-3 flex flex-wrap items-center gap-2">
        <label>Поиск склада <input aria-label="Поиск склада" value={search} disabled={busy || loading} onChange={event => setSearch(event.target.value)} className="rounded-lg border border-line p-2" /></label>
        <button disabled={busy || loading} onClick={() => { setLoading(true); void loadContext(search); }}>Найти склад</button>
        {catalog?.truncated && <p>Показана часть складов. Уточните название для поиска.</p>}
      </div>}
      {locationsLoading && <p role="status">Загрузка ячеек склада…</p>}
      {locationsError && <p role="alert" className="text-red-700">{locationsError}</p>}
      {/* Панель операции */}
      <fieldset disabled={busy || loading || !!contextError || companyChanged || locationsLoading || !!locationsError} className="mt-4 rounded-xl border border-line bg-surface p-4">
        <div className="inline-flex rounded-lg border border-line bg-sunken p-1">
          {OPS.map((o) => (
            <button
              key={o.id}
              onClick={() => { setOp(o.id); setMsg(null); }}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
                op === o.id ? "bg-surface text-accent-ink shadow-sm" : "text-muted",
              )}
            >
              <o.Icon size={15} /> {o.label}
            </button>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <input value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} placeholder="Код SKU*" className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
          <input value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} inputMode="decimal" placeholder={op === "adjustment" ? "Кол-во (±)" : "Кол-во*"} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
          <select aria-label="Склад операции" value={f.warehouse} onChange={e => chooseWarehouse(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink">
            <option value="">Выберите склад</option>
            {catalog?.items.map(warehouse => <option key={warehouse.id} value={warehouse.name}>{warehouse.title}</option>)}
          </select>
          <select aria-label="Из ячейки" value={f.loc} onChange={(e) => setF({ ...f, loc: e.target.value })} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent">
            <option value="">{op === "transfer" ? "Из ячейки" : "Ячейка"}</option>
            {locsForWh.map((l) => <option key={l.id} value={l.id}>{locationLabel(l)}</option>)}
          </select>
          {op === "transfer" ? (
            <select aria-label="В ячейку" value={f.locTo} onChange={(e) => setF({ ...f, locTo: e.target.value })} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent">
              <option value="">В ячейку</option>
              {locsForWh.map((l) => <option key={l.id} value={l.id}>{locationLabel(l)}</option>)}
            </select>
          ) : (
            <input value={f.batch} onChange={(e) => setF({ ...f, batch: e.target.value })} placeholder="Партия" className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
          )}
          <button onClick={submit} disabled={busy} className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60">
            Записать
          </button>
        </div>
        {msg && (
          <p role="alert" className={clsx("mt-2 text-xs", msg.ok ? "text-green-600" : "text-red-600")}>{msg.text}</p>
        )}
      </fieldset>

      {/* Журнал движений */}
      {rows === null ? <p className="mt-4">Журнал ещё не загружен; наличие движений неизвестно.</p> : <MovementsLog rows={rows} />}
    </div>
  );
}
