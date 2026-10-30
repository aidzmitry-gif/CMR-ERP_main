"use client";

import { useInstanceOrganization,withInstanceOrganization } from "@/components/instance-organization-gate";

import { Button } from "@/components/ui/button";
import { useEffect,useState } from "react";

type Warehouse = { id: number; organization_id: number; name: string; title: string; wms_enabled: boolean; prohibit_negative_stock: boolean };

async function responseJson(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось выполнить запрос.");
  return data;
}

function warehouseOptions(data: unknown, organization: string): { items: Warehouse[]; truncated: boolean } {
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Режимы складов не подтверждены сервером. Обновите страницу.");
  const value = data as Record<string, unknown>;
  if (String(value.organization_id) !== organization || !Array.isArray(value.items)) {
    throw new Error("Режимы складов не подтверждены сервером. Обновите страницу.");
  }
  const items = value.items.map((item): Warehouse => {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error("Режимы складов не подтверждены сервером. Обновите страницу.");
    const row = item as Record<string, unknown>;
    if (String(row.organization_id) !== organization || !Number.isSafeInteger(row.id)
      || typeof row.name !== "string" || typeof row.title !== "string" || typeof row.wms_enabled !== "boolean"
      || (row.prohibit_negative_stock !== undefined && typeof row.prohibit_negative_stock !== "boolean")) {
      throw new Error("Режимы складов не подтверждены сервером. Обновите страницу.");
    }
    return { id: row.id as number, organization_id: row.organization_id as number, name: row.name,
      title: row.title, wms_enabled: row.wms_enabled,
      prohibit_negative_stock: row.prohibit_negative_stock === undefined ? true : row.prohibit_negative_stock as boolean };
  });
  return { items, truncated: value.truncated === true };
}

 function WarehouseExecutionSettingsWorkspace() {

  const organization = String(useInstanceOrganization().id);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<Warehouse | null>(null);



  useEffect(() => {
    const controller = new AbortController();
    if (!organization) return () => controller.abort();
    void fetch(`/api/wms/organizations/${organization}/warehouse-options`, { cache: "no-store", signal: controller.signal })
      .then(responseJson).then(data => {
        const parsed = warehouseOptions(data, organization);
        if (!controller.signal.aborted) {
          setWarehouses(parsed.items);
          if (parsed.truncated) setNotice("Показаны первые 50 складов. Настройки остальных здесь не изменяются.");
        }
      }).catch(reason => { if (!controller.signal.aborted) setError(String(reason.message ?? reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [organization, reload]);

  async function changeStockPolicy(row: Warehouse, prohibit: boolean) {
    if (busy || String(row.organization_id) !== organization) return;
    setBusy(true); setError(""); setNotice("");
    let accepted = false;
    try {
      const response = await fetch(`/api/wms/organizations/${organization}/warehouses/${row.id}/stock-policy`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_prohibit_negative_stock: row.prohibit_negative_stock,
          prohibit_negative_stock: prohibit }),
      });
      if (!response.ok) await responseJson(response);
      accepted = true;
      const parsed = warehouseOptions(await responseJson(await fetch(
        `/api/wms/organizations/${organization}/warehouse-options`, { cache: "no-store" })), organization);
      const current = parsed.items.find(item => item.id === row.id);
      if (!current || current.prohibit_negative_stock !== prohibit) {
        throw new Error("Сервер не подтвердил настройку выбранного склада. Обновите список.");
      }
      setWarehouses(parsed.items);
      setNotice(`Склад «${row.title}»: ${prohibit ? "отрицательные остатки запрещены" : "отрицательные остатки разрешены"}.`);
    } catch (reason) {
      setError(accepted
        ? "Изменение отправлено, но состояние не подтверждено. Обновите список перед дальнейшей работой."
        : `${reason instanceof Error ? reason.message : "Не удалось сохранить настройку."} Обновите список для проверки результата.`);
      try {
        const current = warehouseOptions(await responseJson(await fetch(
          `/api/wms/organizations/${organization}/warehouse-options`, { cache: "no-store" })), organization);
        setWarehouses(current.items);
      } catch { /* Keep the last confirmed values and the original refusal visible. */ }
    } finally { setBusy(false); }
  }

  async function changeMode(row: Warehouse) {
    if (busy || String(row.organization_id) !== organization) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await responseJson(await fetch(`/api/wms/organizations/${organization}/warehouses/${row.id}/execution-mode`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wms_enabled: !row.wms_enabled, expected_wms_enabled: row.wms_enabled }),
      }));
      if (data.id !== row.id || data.organization_id !== row.organization_id || data.wms_enabled !== !row.wms_enabled) {
        throw new Error("Ответ не подтверждает выбранный режим. Обновите список перед следующим изменением.");
      }
      setWarehouses(current => current.map(item => item.id === row.id ? data : item));
      setSelected(null);
      setNotice(`Склад «${row.title}»: WMS ${data.wms_enabled ? "включён" : "выключен"}.`);
    } catch (reason) {
      setSelected(null);
      setError(`${reason instanceof Error ? reason.message : "Не удалось сохранить режим."} Обновите список для проверки результата.`);
    } finally { setBusy(false); }
  }

  return <section className="space-y-5">
    <h1 className="text-2xl font-semibold">Режим работы склада</h1>
    <p>Без WMS списание оформляется по документу. С WMS движение подтверждается складским процессом. Новые склады создаются с выключенным WMS.</p>
    <p className="text-sm text-muted">Изменять режим может главный бухгалтер с правом управления складом. Сначала завершите открытые резервы и складские задания. История проведённых операций сохраняется.</p>
    <span className="text-sm text-muted">Юрлицо задано в настройках.</span>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {loading && <p>Загрузка режимов…</p>}
    {organization && !loading && !error && !warehouses.length && <p>Доступных складов нет.</p>}
    {warehouses.map(row => <div key={row.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
      <div><h2 className="font-semibold">{row.title}</h2><p>{row.name} · WMS {row.wms_enabled ? "включён" : "выключен"}</p>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input type="checkbox" aria-label={`Запрещать отрицательные остатки для склада ${row.title}`}
            checked={row.prohibit_negative_stock} disabled={busy || loading}
            onChange={event => void changeStockPolicy(row, event.target.checked)} />
          Запрещать отрицательные остатки
        </label>
      </div>
      <Button variant="secondary" disabled={busy || loading} onClick={() => setSelected(row)}>{row.wms_enabled ? "Выключить WMS" : "Включить WMS"}</Button>
    </div>)}
    {selected && <div className="space-y-3 rounded-xl border border-accent p-4">
      <p>{selected.wms_enabled ? "Выключить" : "Включить"} WMS для склада «{selected.title}»?</p>
      <p>Изменение относится только к новым операциям этого склада. Сервер проверит отсутствие незавершённых операций.</p>
      <Button disabled={busy} onClick={() => void changeMode(selected)}>Подтвердить изменение режима</Button>{" "}
      <Button variant="secondary" disabled={busy} onClick={() => setSelected(null)}>Отмена</Button>
    </div>}
    {organization && <Button variant="secondary" disabled={busy || loading} onClick={() => {
      setWarehouses([]); setSelected(null); setError(""); setNotice("");
      setLoading(true); setReload(value => value + 1);
    }}>Обновить список</Button>}
  </section>;
}

export const WarehouseExecutionSettings = withInstanceOrganization(WarehouseExecutionSettingsWorkspace);
