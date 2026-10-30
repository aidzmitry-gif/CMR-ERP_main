"use client";

import clsx from "clsx";
import { Plus, Printer } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createLocation, fetchLocations, fetchLocationWarehouses, LocationRequestError, locationLabel, type LocationOrganization, type WmsLocation } from "@/lib/wms-ops";

const control = "rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink disabled:opacity-60";
const message = (error: unknown) => error instanceof Error ? error.message : "Не удалось загрузить данные ячеек.";

export function WmsLocations({ initial, organizations }: { initial: WmsLocation[]; organizations: LocationOrganization[] }) {
  const [company, setCompany] = useState("");
  const [posting, setPosting] = useState(false);
  const [overviewFresh, setOverviewFresh] = useState(false);
  return <div className="flex-1 overflow-auto p-6">
    <p className="text-sm text-muted">Ячейки принадлежат компании и зарегистрированному складу. Общий обзор предназначен для просмотра.</p>
    <label className="mt-4 flex max-w-lg flex-col gap-1 text-sm text-muted">Компания
      <select aria-label="Компания ячеек" value={company} disabled={posting} onChange={(event) => { setOverviewFresh(true); setCompany(event.target.value); }} className={control}>
        <option value="">Все доступные компании · обзор</option>
        {organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
      </select>
    </label>
    <LocationScope key={company || "overview"} organizationId={company ? Number(company) : undefined} initial={company ? [] : initial} organizations={organizations} refreshOnMount={overviewFresh} onPosting={setPosting} />
  </div>;
}

function LocationScope({ organizationId, initial, organizations, refreshOnMount, onPosting }: {
  organizationId?: number; initial: WmsLocation[]; organizations: LocationOrganization[]; refreshOnMount: boolean; onPosting: (value: boolean) => void;
}) {
  const [rows, setRows] = useState(initial);
  const [loading, setLoading] = useState(organizationId != null || refreshOnMount);
  const [readError, setReadError] = useState("");
  const [warehouses, setWarehouses] = useState<{ name: string }[]>([]);
  const [warehouseError, setWarehouseError] = useState("");
  const [warehouseBusy, setWarehouseBusy] = useState(organizationId != null);
  const [truncated, setTruncated] = useState(false);
  const [term, setTerm] = useState("");
  const [form, setForm] = useState({ warehouse: "", zone: "", code: "", title: "" });
  const [busy, setBusy] = useState(false);
  const [writeError, setWriteError] = useState("");
  const [saved, setSaved] = useState("");
  const [unknownWrite, setUnknownWrite] = useState(false);
  const alive = useRef(true);
  const serial = useRef(false);
  const reads = useRef(0);
  const searches = useRef(0);

  async function refresh() {
    const generation = ++reads.current;
    setLoading(true); setRows([]); setReadError("");
    try {
      const next = await fetchLocations(organizationId);
      if (!alive.current || generation !== reads.current) return;
      setRows(next); setUnknownWrite(false);
    } catch (error) {
      if (alive.current && generation === reads.current) setReadError(message(error));
    } finally {
      if (alive.current && generation === reads.current) setLoading(false);
    }
  }

  async function search(query: string) {
    if (organizationId == null) return;
    const generation = ++searches.current;
    setWarehouseBusy(true); setWarehouses([]); setWarehouseError(""); setTruncated(false);
    setForm((previous) => ({ ...previous, warehouse: "" }));
    try {
      const next = await fetchLocationWarehouses(organizationId, query);
      if (!alive.current || generation !== searches.current) return;
      setWarehouses(next.items); setTruncated(next.truncated);
    } catch (error) {
      if (alive.current && generation === searches.current) setWarehouseError(error instanceof LocationRequestError && error.status === 403
        ? "Создание ячеек для выбранной компании недоступно. Список доступных ячеек можно просматривать." : message(error));
    } finally {
      if (alive.current && generation === searches.current) setWarehouseBusy(false);
    }
  }

  useEffect(() => {
    alive.current = true;
    const read = ++reads.current;
    const catalogue = ++searches.current;
    if (organizationId != null || refreshOnMount) {
      void fetchLocations(organizationId).then((next) => {
        if (alive.current && read === reads.current) setRows(next);
      }).catch((error: unknown) => {
        if (alive.current && read === reads.current) setReadError(message(error));
      }).finally(() => {
        if (alive.current && read === reads.current) setLoading(false);
      });
    }
    if (organizationId != null) {
      void fetchLocationWarehouses(organizationId, "").then((next) => {
        if (alive.current && catalogue === searches.current) { setWarehouses(next.items); setTruncated(next.truncated); }
      }).catch((error: unknown) => {
        if (alive.current && catalogue === searches.current) setWarehouseError(error instanceof LocationRequestError && error.status === 403
          ? "Создание ячеек для выбранной компании недоступно. Список доступных ячеек можно просматривать." : message(error));
      }).finally(() => {
        if (alive.current && catalogue === searches.current) setWarehouseBusy(false);
      });
    }
    return () => { alive.current = false; };
  }, [organizationId, refreshOnMount]);

  async function add() {
    if (serial.current || organizationId == null || unknownWrite) return;
    setWriteError(""); setSaved("");
    if (!form.code.trim() || !warehouses.some((warehouse) => warehouse.name === form.warehouse)) {
      setWriteError("Выберите зарегистрированный склад и заполните код ячейки."); return;
    }
    serial.current = true; setBusy(true); onPosting(true);
    try {
      const row = await createLocation({ organization_id: organizationId, warehouse: form.warehouse, zone: form.zone.trim(), code: form.code.trim(), title: form.title.trim() });
      if (!alive.current) return;
      setRows((previous) => [...previous.filter((item) => item.id !== row.id), row]);
      setForm((previous) => ({ ...previous, code: "", title: "" }));
      setSaved(`Ячейка ${row.code} сохранена.`);
    } catch (error) {
      if (!alive.current) return;
      setWriteError(message(error));
      if (error instanceof LocationRequestError && error.resultUnknown) setUnknownWrite(true);
      if (error instanceof LocationRequestError && (error.status === 401 || error.status === 403)) {
        setRows([]); setReadError(message(error)); setWarehouses([]);
      }
    } finally {
      serial.current = false;
      if (alive.current) { setBusy(false); onPosting(false); }
    }
  }

  const visible = rows.filter((row) => organizations.some((org) => org.id === row.organization_id) && (organizationId == null || row.organization_id === organizationId));
  return <>
    <button type="button" onClick={() => void refresh()} disabled={busy || loading} className={`${control} mt-3`}>Обновить список</button>
    {loading && <p role="status" className="mt-3 text-sm text-muted">Загрузка ячеек…</p>}
    {readError && <p role="alert" className="mt-3 text-sm text-red-600">{readError}</p>}
    {!loading && !readError && <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full text-sm"><thead><tr className="border-b border-line text-left text-xs text-muted">
        {["Компания", "Склад", "Зона", "Ячейка", "Описание", "Статус", ""].map((title, index) => <th key={index} className="px-4 py-2 font-medium">{title}</th>)}
      </tr></thead><tbody>
        {visible.length === 0 && <tr><td colSpan={7} className="px-4 py-6 text-center text-muted">Ячеек в выбранном обзоре нет</td></tr>}
        {visible.map((row) => <tr key={row.id} className="border-b border-line last:border-0">
          <td className="px-4 py-2.5">{organizations.find((org) => org.id === row.organization_id)!.name}</td>
          <td className="whitespace-nowrap px-4 py-2.5">{row.warehouse}</td><td className="px-4 py-2.5">{row.zone || "—"}</td>
          <td className="whitespace-nowrap px-4 py-2.5 font-mono">{locationLabel(row)}</td><td className="px-4 py-2.5">{row.title || "—"}</td>
          <td className="px-4 py-2.5"><span className={clsx("rounded-md px-2 py-0.5 text-xs", row.is_active ? "bg-green-50 text-green-600" : "bg-sunken text-muted")}>{row.is_active ? "Активна" : "Архив"}</span></td>
          <td className="px-4 py-2.5"><Link href={`/erp/wms/locations/${row.id}/label`} className="inline-flex items-center gap-1 whitespace-nowrap"><Printer size={13} /> Этикетка</Link></td>
        </tr>)}
      </tbody></table>
    </div>}
    {organizationId == null ? <p className="mt-4 text-sm text-muted">Для создания ячейки выберите компанию, затем зарегистрированный склад.</p> : <section className="mt-5 rounded-xl border border-line bg-surface p-4" aria-label="Новая ячейка">
      <h2 className="font-semibold text-ink">Новая ячейка</h2>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-sm text-muted">Поиск склада<input aria-label="Поиск склада" maxLength={100} value={term} disabled={busy || warehouseBusy} onChange={(event) => setTerm(event.target.value)} className={control} /></label>
        <button type="button" disabled={busy || warehouseBusy} onClick={() => void search(term)} className={control}>Найти склады</button>
      </div>
      {warehouseBusy && <p role="status" className="mt-2 text-sm text-muted">Загрузка складов…</p>}
      {warehouseError && <p className="mt-2 text-sm text-red-600">{warehouseError}</p>}
      {truncated && <p className="mt-2 text-sm text-muted">Показаны первые 50 складов. Уточните поиск, если нужного склада нет.</p>}
      {!warehouseBusy && !warehouseError && warehouses.length === 0 && <p className="mt-2 text-sm text-muted">Зарегистрированные склады не найдены. Уточните поиск или обратитесь к ответственному за справочник складов.</p>}
      <fieldset disabled={busy || loading || !!readError || warehouseBusy || !!warehouseError || unknownWrite} className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-muted">Склад<select aria-label="Склад ячейки" className={control} value={form.warehouse} onChange={(event) => setForm({ ...form, warehouse: event.target.value })}>
          <option value="">Выберите склад</option>{warehouses.map((warehouse) => <option key={warehouse.name} value={warehouse.name}>{warehouse.name}</option>)}
        </select></label>
        <label className="flex flex-col gap-1 text-sm text-muted">Зона<input placeholder="Зона" className={control} value={form.zone} onChange={(event) => setForm({ ...form, zone: event.target.value })} /></label>
        <label className="flex flex-col gap-1 text-sm text-muted">Код ячейки<input placeholder="Ячейка*" aria-invalid={!!writeError} className={clsx(control, writeError && "border-amber-500")} value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} /></label>
        <label className="flex flex-col gap-1 text-sm text-muted">Описание<input placeholder="Описание" className={control} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
        <button type="button" onClick={() => void add()} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm text-white disabled:opacity-60"><Plus size={15} />{busy ? "Сохранение…" : "Добавить"}</button>
      </fieldset>
      {writeError && <p role="alert" className="mt-3 text-sm text-red-600">{writeError}</p>}
      {saved && <p role="status" className="mt-3 text-sm text-green-600">{saved}</p>}
      {unknownWrite && <p className="mt-2 text-sm text-muted">Сначала обновите список и проверьте, была ли создана ячейка. Повторная отправка может создать дубль.</p>}
    </section>}
  </>;
}
