"use client";

import clsx from "clsx";
import { ArrowRight, FileText, RefreshCw, Search, Truck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { OfficeShippingWorkspace } from "@/components/erp/office-shipping-workspace";
import { fetchOfficeDocuments, type OfficeDocument } from "@/lib/office-shipping-api";

export const OFFICE_STAGE_LABELS: Record<string, string> = {
  draft: "Черновик", ready: "Готов к подготовке", shipped: "Отгрузка оформлена",
  await_pay: "Ожидание оплаты", paid: "Оплачен", docs: "Документы",
};

export function OfficeDelivery({ onReconciled }: { onReconciled?: () => void }) {
  const [rows, setRows] = useState<OfficeDocument[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let alive = true;
    void fetchOfficeDocuments(controller.signal).then(value => {
      if (alive) { setRows(value); setState("ready"); }
    }).catch(e => { if (alive && !controller.signal.aborted) { setError(e instanceof Error ? e.message : "Не удалось загрузить документы."); setState("error"); } });
    return () => { alive = false; controller.abort(); };
  }, [revision]);
  const visible = useMemo(() => {
    const term = query.trim().toLocaleLowerCase("ru");
    return rows.filter(row => `${row.number} ${row.company} ${row.title}`.toLocaleLowerCase("ru").includes(term));
  }, [rows, query]);
  const document = rows.find(row => row.id === selected);
  return (
    <main className="min-w-0 flex-1 overflow-y-auto bg-canvas p-3 sm:p-6" aria-label="Доставка офиса">
      <div className="mx-auto max-w-[1440px] space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-accent-ink"><Truck size={15} /> Офис · логистика</div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">Заявки на доставку</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted">Выберите документ, подготовьте условия и подтвердите связь со счётом. Состояние доставки поступает из логистики.</p>
          </div>
          <button type="button" onClick={() => { setState("loading"); setRows([]); setSelected(null); setRevision(v => v + 1); }} disabled={state === "loading"} className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink disabled:opacity-50"><RefreshCw size={15} /> Обновить список</button>
        </header>
        {state === "loading" && <p role="status" className="rounded-xl border border-line bg-surface p-6 text-sm text-muted">Загрузка доступных документов…</p>}
        {state === "error" && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">{error}</div>}
        {state === "ready" && rows.length === 0 && <div className="rounded-xl border border-dashed border-line bg-surface p-8"><FileText className="mb-3 text-faint" size={28} /><h2 className="font-semibold text-ink">Нет доступных документов</h2><p className="mt-1 text-sm text-muted">Документы появятся после создания и назначения проверяющего. Назначения доступны на вкладке «Проверяющие».</p></div>}
        {state === "ready" && rows.length > 0 && <div className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(240px,310px)_minmax(0,1fr)]">
          <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-surface" aria-label="Выбор документа">
            <div className="border-b border-line p-4"><div className="mb-3 flex items-center justify-between text-sm"><h2 className="font-semibold text-ink">Документы</h2><span className="text-muted">{rows.length}</span></div><label className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-muted"><Search size={15} /><input aria-label="Поиск документа" value={query} onChange={e => setQuery(e.target.value)} placeholder="Номер или компания" className="w-full min-w-0 bg-transparent text-sm text-ink outline-none" /></label></div>
            <div className="max-h-80 overflow-y-auto xl:max-h-[650px]">{visible.map(row => <button type="button" key={row.id} onClick={() => setSelected(row.id)} aria-pressed={selected === row.id} className={clsx("flex w-full items-start gap-3 border-b border-line p-4 text-left last:border-0", selected === row.id ? "bg-accent-soft" : "hover:bg-sunken")}>
              <div className="min-w-0 flex-1"><p className="break-words text-sm font-semibold text-ink">{row.number || `Документ #${row.id}`}</p><p className="mt-0.5 break-words text-sm text-muted">{row.company || "Компания не указана"}</p><span className="mt-2 inline-flex rounded bg-sunken px-2 py-0.5 text-xs text-muted">{OFFICE_STAGE_LABELS[row.stage] || `Этап: ${row.stage}`}</span></div><ArrowRight size={15} className="mt-1 shrink-0 text-faint" />
            </button>)}{visible.length === 0 && <p className="p-5 text-sm text-muted">По этому запросу документы не найдены.</p>}</div>
          </section>
          {document ? <OfficeShippingWorkspace key={document.id} document={document} onReconciled={() => { setRevision(v => v + 1); onReconciled?.(); }} /> : <div className="rounded-xl border border-dashed border-line bg-surface p-7 sm:p-10"><Truck size={30} className="mb-4 text-accent-ink" /><h2 className="text-lg font-semibold text-ink">Откройте документ в списке</h2><p className="mt-2 max-w-lg text-sm leading-6 text-muted">В карточке будут условия заявки, точный счёт и подтверждённый статус исполнения. Оплата и оформление документов отображаются в своей воронке.</p></div>}
        </div>}
      </div>
    </main>
  );
}
