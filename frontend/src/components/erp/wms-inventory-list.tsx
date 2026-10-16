"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { createInventory, fetchInventoryList, type InventoryCount, type InventoryOrganization, inventoryStatusLabel } from "@/lib/wms-inventory";
import { emptySourceDraft, InventoryOrganizationSelect, InventorySourceFields, sourcePayload, sourceReady, useInventoryRequestScope } from "./wms-inventory-source";

interface Props { initial: InventoryCount[]; organizations: InventoryOrganization[]; initialOrganizationId: number | null }
export function WmsInventoryList(props: Props) {
  return <InventoryListBody key={JSON.stringify([props.initialOrganizationId, props.initial])} {...props} />;
}

function InventoryListBody({ initial, organizations, initialOrganizationId }: Props) {
  const router = useRouter();
  const request = useInventoryRequestScope();
  const [organizationId, setOrganizationId] = useState(initialOrganizationId);
  const [docs, setDocs] = useState<InventoryCount[] | null>(initialOrganizationId === null ? null : initial);
  const [warehouse, setWarehouse] = useState("");
  const [source, setSource] = useState(emptySourceDraft);

  async function changeOrganization(id: number | null) {
    const ticket = request.begin();
    setOrganizationId(id); setDocs(null); setSource(emptySourceDraft());
    try {
      if (id !== null) { const rows = await fetchInventoryList(id); if (request.current(ticket)) setDocs(rows); }
    } catch (error) { request.fail(ticket, error); }
    finally { request.finish(ticket); }
  }
  async function onCreate() {
    if (request.busy || organizationId === null || !warehouse.trim() || !sourceReady(source)) return;
    const ticket = request.begin();
    try {
      const doc = await createInventory({ organization_id: organizationId, warehouse: warehouse.trim(), ...sourcePayload(source) });
      if (request.current(ticket)) router.push(`/erp/wms/inventory/${doc.id}`);
    } catch (error) { request.fail(ticket, error); }
    finally { request.finish(ticket); }
  }
  return <div className="min-w-0 flex-1 overflow-auto p-6">
    <p className="mb-4 text-sm text-muted">Пересчёт физического журнала склада выбранного юрлица. Неизвестный остаток не считается нулём.</p>
    <InventoryOrganizationSelect organizations={organizations} value={organizationId} onChange={changeOrganization} />
    <label className="mt-4 block text-sm">Склад
      <input aria-label="Склад" value={warehouse} onChange={(e) => { setWarehouse(e.target.value); setSource({ ...source, confirmed: false }); }}
        className="ml-2 rounded-lg border border-line bg-surface px-3 py-2" />
    </label>
    <InventorySourceFields draft={source} onChange={setSource} disabled={request.busy || organizationId === null} />
    <button onClick={onCreate} disabled={request.busy || organizationId === null || !warehouse.trim() || !sourceReady(source)}
      className="mt-3 rounded-lg bg-accent px-3 py-2 text-sm text-white disabled:opacity-60">Новая инвентаризация</button>
    {request.error && <div role="alert" className="mt-3 text-sm text-red-600">{request.error}
      {organizationId !== null && <button className="ml-2 underline" onClick={() => changeOrganization(organizationId)}>Повторить загрузку списка</button>}
    </div>}
    {request.busy && <p role="status" className="mt-3 text-sm">Выполняется запрос…</p>}
    {organizationId === null ? <p className="mt-4 text-sm text-muted">Выберите юрлицо для просмотра документов.</p> : docs !== null &&
      <div className="mt-4 overflow-auto rounded-xl border border-line bg-surface"><table className="w-full text-sm">
        <thead><tr><th className="p-3 text-left">Документ</th><th className="p-3 text-left">Склад</th><th className="p-3 text-left">Статус</th><th className="p-3 text-left">Источник</th></tr></thead>
        <tbody>{docs.length === 0 && !request.error && <tr><td colSpan={4} className="p-4 text-muted">Инвентаризаций пока нет</td></tr>}
          {docs.filter((doc) => doc.organization_id === organizationId).map((doc) => <tr key={doc.id} className="border-t border-line">
            <td className="p-3"><Link className="text-accent-ink underline" href={`/erp/wms/inventory/${doc.id}`}>{doc.number || `ИНВ-${doc.id}`}</Link></td>
            <td className="p-3">{doc.warehouse}</td><td className="p-3">{inventoryStatusLabel(doc.status)}</td>
            <td className="p-3">{doc.expected_source === "wms_physical" ? "Физический журнал WMS" : "Не подтверждён"}</td>
          </tr>)}
        </tbody></table></div>}
  </div>;
}
