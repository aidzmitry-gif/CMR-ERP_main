"use client";

import { useInstanceOrganization,withInstanceOrganization } from "@/components/instance-organization-gate";

import { useEffect,useRef,useState } from "react";

import { Card,KpiTile } from "@/components/erp/logistics-ui";
import { logisticsReadMessage } from "@/lib/logistics-api";
import {
fetchCostCatalog,fetchOwnedCostReview,formatFreightByn,
type CostCatalog,type CostSelection,type OwnedCostReview,
} from "@/lib/logistics-owned-costs";

function LogisticsInsightsWorkspace() {
  const organization = useInstanceOrganization();
  const epoch = useRef(0);
  const [foreground, setForeground] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [catalog, setCatalog] = useState<CostCatalog | null>(null);
  const [selected, setSelected] = useState<CostSelection | null>(null);
  const [result, setResult] = useState<{ selected: CostSelection; data: OwnedCostReview } | null>(null);
  const [error, setError] = useState("");

  function invalidate() {
    epoch.current += 1;
    setCatalog(null);
    setResult(null);
    setError("");
    setRefresh(value => value + 1);
  }

  useEffect(() => {
    function hide() {
      epoch.current += 1;
      setForeground(false);
      setCatalog(null);
      setResult(null);
      setError("");
    }
    function revalidate() {
      hide();
      setRefresh(value => value + 1);
      setForeground(!document.hidden && document.hasFocus());
    }
    revalidate();
    window.addEventListener("blur", hide);
    window.addEventListener("focus", revalidate);
    document.addEventListener("visibilitychange", revalidate);
    return () => {
      window.removeEventListener("blur", hide);
      window.removeEventListener("focus", revalidate);
      document.removeEventListener("visibilitychange", revalidate);
    };
  }, []);

  useEffect(() => {
    if (!foreground) return;
    let active = true;
    const generation = epoch.current;
    const controller = new AbortController();
    void fetchCostCatalog(controller.signal).then(value => {
      if (!active || epoch.current !== generation) return;
      setCatalog(value);
      setSelected(value.items.some(item => item.id === organization.id)
        ? { organization_id: organization.id, principal: value.principal } : null);
      if (!value.items.some(item => item.id === organization.id)) setError("Нет доступа к данным юрлица установки.");
    }).catch(reason => { if (active && epoch.current === generation) setError(logisticsReadMessage(reason)); });
    return () => { active = false; controller.abort(); };
  }, [foreground, refresh, organization.id]);

  useEffect(() => {
    if (!foreground || !catalog || !selected || selected.principal !== catalog.principal) return;
    let active = true;
    const generation = epoch.current;
    const controller = new AbortController();
    void fetchOwnedCostReview(selected, controller.signal).then(data => {
      if (!active || epoch.current !== generation) return;
      if (data.organization_id !== selected.organization_id || data.principal !== selected.principal) {
        setError("Не удалось подтвердить владельца ответа. Обновите доступ.");
        return;
      }
      setResult({ selected, data });
    }).catch(reason => { if (active && epoch.current === generation) setError(logisticsReadMessage(reason)); });
    return () => { active = false; controller.abort(); };
  }, [foreground, catalog, selected]);

  const data = foreground && catalog && result?.selected === selected ? result.data : null;
  const freight = data?.import_freight;
  return <section aria-label="Аналитика стоимости по юрлицу" className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold text-ink">Аналитика стоимости по юрлицу</h2>
      <button className="rounded-lg border border-line px-3 py-2 text-sm text-ink" onClick={invalidate}>Обновить</button>
    </div>
    {!foreground ? <p role="status">Данные скрыты до проверки доступа.</p> : <>
      {error && <p role="alert" className="rounded-xl bg-surface p-4 text-sm text-red-600">{error}</p>}
      {!catalog && !error && <p role="status">Проверка доступа к юрлицам…</p>}
      {catalog && <>
        <p className="text-sm text-muted">Используется юрлицо установки.</p>
        {!catalog.items.length ? <p>Нет доступных юрлиц для просмотра затрат.</p>
          : !selected && <p>Нет подтверждённого доступа к источникам фрахта юрлица установки.</p>}
        {selected && !data && !error && <p role="status">Загрузка фрахта выбранного юрлица…</p>}
      </>}
      {freight && <>
        <Card title="Импорт-фрахт" hint="По суммам подтверждённых собственных поставок на стадии «Склад». Бухгалтерские проводки этим отчётом не подтверждены.">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile label="Известный фрахт" value={formatFreightByn(freight.known_total)} tone="brand" />
            <KpiTile label="Поставок с известной ценой" value={freight.known_count} />
            <KpiTile label="Средний известный фрахт" value={formatFreightByn(freight.known_average)} />
            <KpiTile label="Итог по подтверждённым поставкам" value={formatFreightByn(freight.total)} />
          </div>
          <p className="mt-3 text-sm text-muted">Подтверждено источников: {freight.qualified_import_count}; на складе: {freight.warehouse_import_count}; вне стадии «Склад»: {freight.excluded_nonwarehouse_count}.</p>
          {!freight.qualified_import_count && <p className="mt-2 text-sm text-muted">Нет подтверждённых источников для расчёта. Расходы не определены.</p>}
          {freight.unpriced_count > 0 && <p role="alert" className="mt-2 text-sm text-amber-700">Не оценён фрахт поставок: {freight.unpriced_count}. Общий итог не определён.</p>}
        </Card>
        <p className="text-sm text-muted">Охват затрат неполный. Показатели других разделов ожидают подтверждения источников.</p>
        <div className="grid gap-3 md:grid-cols-3">
          {["Тарифы и экономия по зонам", "Экономия по тендерам", "Возвраты по аудиту"].map(title =>
            <Card key={title} title={title}><p className="text-sm text-muted">Нет подтверждённого сопоставления источников с юрлицом. Показатель не определён.</p></Card>)}
        </div>
      </>}
    </>}
  </section>;
}

export const LogisticsInsights = withInstanceOrganization(LogisticsInsightsWorkspace);
