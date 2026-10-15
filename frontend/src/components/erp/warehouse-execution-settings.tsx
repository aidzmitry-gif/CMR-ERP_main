"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

type Organization = { id: number; name: string };
type Warehouse = { id: number; organization_id: number; name: string; title: string; wms_enabled: boolean };

async function responseJson(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось выполнить запрос.");
  return data;
}

export function WarehouseExecutionSettings() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [organization, setOrganization] = useState("");
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<Warehouse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/accounting/organizations", { cache: "no-store", signal: controller.signal })
      .then(responseJson).then((rows: Organization[]) => {
        if (!Array.isArray(rows) || rows.some(row => !Number.isSafeInteger(row.id) || typeof row.name !== "string")) {
          throw new Error("Не удалось проверить список организаций.");
        }
        if (!controller.signal.aborted) setOrganizations(rows);
      }).catch(reason => { if (!controller.signal.aborted) setError(String(reason.message ?? reason)); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (!organization) return () => controller.abort();
    void fetch(`/api/wms/organizations/${organization}/warehouse-options`, { cache: "no-store", signal: controller.signal })
      .then(responseJson).then(data => {
        if (String(data.organization_id) !== organization || !Array.isArray(data.items)
          || data.items.some((row: Warehouse) => String(row.organization_id) !== organization
            || !Number.isSafeInteger(row.id) || typeof row.name !== "string"
            || typeof row.title !== "string" || typeof row.wms_enabled !== "boolean")) {
          throw new Error("Режимы складов не подтверждены сервером. Обновите страницу.");
        }
        if (!controller.signal.aborted) {
          setWarehouses(data.items);
          if (data.truncated) setNotice("Показаны первые 50 складов. Настройки остальных здесь не изменяются.");
        }
      }).catch(reason => { if (!controller.signal.aborted) setError(String(reason.message ?? reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [organization, reload]);

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
    <label className="block">Организация
      <select className="ml-3 rounded border border-line p-2" value={organization} disabled={busy} onChange={event => {
        setWarehouses([]); setSelected(null); setError(""); setNotice("");
        setLoading(Boolean(event.target.value)); setOrganization(event.target.value);
      }}>
        <option value="">Выберите организацию</option>
        {organizations.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
      </select>
    </label>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {loading && <p>Загрузка режимов…</p>}
    {organization && !loading && !error && !warehouses.length && <p>Доступных складов нет.</p>}
    {warehouses.map(row => <div key={row.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
      <div><h2 className="font-semibold">{row.title}</h2><p>{row.name} · WMS {row.wms_enabled ? "включён" : "выключен"}</p></div>
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
