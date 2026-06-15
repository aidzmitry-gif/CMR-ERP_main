"use client";

import { Bot, Clock, Database, Layers, Loader2, Search, TreePine } from "lucide-react";
import { useState } from "react";

import type { AiCatalog, AiReference, ReferenceQueryResult } from "@/lib/reference-data";
import { runReferenceQuery } from "@/lib/reference-data";
import { FALLBACK_CATALOG, buildQueryInput } from "@/lib/spravochniki-ai";

const DEMO_BADGE = (
  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">демо</span>
);

function RefIcon({ ref }: { ref: AiReference }) {
  if (ref.versioned) return <Clock className="h-3.5 w-3.5 shrink-0 text-muted" />;
  if (ref.key.includes("group") || ref.key.includes("categor")) return <TreePine className="h-3.5 w-3.5 shrink-0 text-muted" />;
  return <Bot className="h-3.5 w-3.5 shrink-0 text-brand" />;
}

function CatalogEntry({ ref, active, onClick }: { ref: AiReference; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "w-full rounded-xl border px-3 py-2.5 text-left transition-colors",
        active
          ? "border-brand/30 bg-brand/5"
          : "border-slate-100 bg-white hover:border-brand/20 hover:bg-slate-50",
      ].join(" ")}
    >
      <div className="flex items-center gap-1.5">
        <RefIcon ref={ref} />
        <span className="text-sm font-semibold text-ink">{ref.title}</span>
        {ref.versioned && (
          <span className="ml-auto rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-muted">SCD2</span>
        )}
      </div>
      <div className="mt-0.5 font-mono text-[11px] text-slate-500">{ref.endpoint}</div>
      <p className="mt-1 text-[12px] text-muted">{ref.description}</p>
    </button>
  );
}

function ResultDisplay({ result }: { result: ReferenceQueryResult }) {
  const formatted = JSON.stringify(result.result, null, 2);
  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600">
          ref: {result.ref}
        </span>
        {result.as_of && (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
            на дату {result.as_of}
          </span>
        )}
        {result.key && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600">
            key: {result.key}
          </span>
        )}
      </div>
      <pre className="max-h-56 overflow-auto rounded-xl bg-slate-900 p-3 text-[12px] leading-relaxed text-slate-200">
        {formatted}
      </pre>
    </div>
  );
}

export function SpravAi({ initial }: { initial: AiCatalog | null }) {
  const isDemo = initial === null;
  const catalog = initial ?? FALLBACK_CATALOG;

  const [selectedRef, setSelectedRef] = useState<string>(catalog.references[0]?.key ?? "");
  const [key, setKey] = useState("");
  const [asOf, setAsOf] = useState("");
  const [name, setName] = useState("");
  const [limit, setLimit] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ReferenceQueryResult | null>(null);
  const [queryError, setQueryError] = useState(false);

  async function handleQuery(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedRef) return;
    setLoading(true);
    setResult(null);
    setQueryError(false);
    const res = await runReferenceQuery(buildQueryInput({ ref: selectedRef, key, as_of: asOf, name, limit }));
    setLoading(false);
    if (res) setResult(res);
    else setQueryError(true);
  }

  const selectedMeta = catalog.references.find((r) => r.key === selectedRef);

  return (
    <div className="mx-auto max-w-[1280px] space-y-4 p-4">
      {/* Title */}
      <div>
        <h1 className="text-xl font-bold text-ink">Как AI работает со справочниками</h1>
        <p className="mt-1 text-sm text-muted">
          Структурный доступ (SQL/MCP) для точности и историчности; эмбеддинги — только нечёткий поиск.
        </p>
      </div>

      {/* Info bar */}
      <div className="rounded-2xl bg-brand/10 p-4 text-sm text-slate-700 shadow-card">
        AI берёт точные значения <span className="font-semibold">структурно</span> поверх semantic-слоя
        · историчность учитывается <span className="font-semibold">(на дату)</span>
        · pgvector — только «похоже на…»,{" "}
        <span className="font-semibold">не для точных полей</span>.
        {isDemo && (
          <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800">
            бэкенд недоступен — {DEMO_BADGE}
          </span>
        )}
      </div>

      {/* Main grid: catalog + query form */}
      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">

        {/* Left: AI catalog */}
        <div className="rounded-2xl bg-white p-5 shadow-card">
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Каталог для AI
            </div>
            <div className="flex items-center gap-1">
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
                🤖 ai_exposed
              </span>
              {isDemo && DEMO_BADGE}
            </div>
          </div>
          <div className="mt-0.5 font-mono text-[11px] text-slate-500">
            GET {catalog.tool.endpoint.replace("/query", "/ai-catalog")}
          </div>

          <div className="mt-4 space-y-2">
            {catalog.references.map((ref) => (
              <CatalogEntry
                key={ref.key}
                ref={ref}
                active={ref.key === selectedRef}
                onClick={() => setSelectedRef(ref.key)}
              />
            ))}
            {catalog.references.length === 0 && (
              <p className="py-6 text-center text-sm text-muted">Нет доступных справочников</p>
            )}
          </div>
        </div>

        {/* Right: interactive query */}
        <div className="rounded-2xl bg-white p-5 shadow-card">
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Структурный запрос
            </div>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 font-mono text-[11px] text-blue-700">
              {catalog.tool.name}
            </span>
          </div>
          <p className="mt-1 text-[12px] text-muted">{catalog.tool.note}</p>

          <form onSubmit={handleQuery} className="mt-4 space-y-3">
            {/* ref select */}
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                ref *
              </label>
              <select
                value={selectedRef}
                onChange={(e) => { setSelectedRef(e.target.value); setResult(null); setQueryError(false); }}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-sm text-ink focus:border-brand focus:outline-none"
              >
                {catalog.references.map((r) => (
                  <option key={r.key} value={r.key}>{r.title} — {r.key}</option>
                ))}
              </select>
            </div>

            {/* Columns hint */}
            {selectedMeta && (
              <div className="flex flex-wrap gap-1">
                {selectedMeta.columns.map((c) => (
                  <span key={c.name} className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-500">
                    {c.name}: {c.type}
                  </span>
                ))}
              </div>
            )}

            {/* Optional fields row */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  key
                </label>
                <input
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder="напр. USD, НДС"
                  className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-ink placeholder:text-slate-300 focus:border-brand focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  as_of {selectedMeta?.versioned && <span className="text-amber-600">(SCD2)</span>}
                </label>
                <input
                  type="date"
                  value={asOf}
                  onChange={(e) => setAsOf(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  name (поиск)
                </label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="напр. Ромашка"
                  className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-ink placeholder:text-slate-300 focus:border-brand focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  limit
                </label>
                <input
                  type="number"
                  min={1}
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                  placeholder="10"
                  className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-ink placeholder:text-slate-300 focus:border-brand focus:outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={!selectedRef || loading}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Выполнить запрос
            </button>
          </form>

          {/* Result */}
          {queryError && (
            <div className="mt-3 rounded-xl border border-amber-100 bg-amber-50/60 px-4 py-3 text-[13px] text-amber-800">
              Бэкенд недоступен или вернул ошибку — проверьте, запущен ли сервер.
            </div>
          )}
          {result && <ResultDisplay result={result} />}
        </div>
      </div>

      {/* Bottom: semantic layer + pgvector */}
      <div className="grid gap-4 lg:grid-cols-2">

        {/* Semantic layer (light) */}
        <div className="rounded-2xl bg-white p-5 shadow-card">
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Semantic / metrics-слой
            </div>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
              точка входа AI
            </span>
          </div>
          <p className="mt-1 text-[12px] text-muted">
            AI ходит сюда за определениями сущностей и метрик, не в сырую схему.
          </p>

          <div className="mt-4 divide-y divide-slate-50 text-sm">
            {[
              {
                title: "Контрагент",
                desc: "Эталонная карточка (golden record) по natural key УНП + код ERP; алиасы и id 1С склеены.",
              },
              {
                title: "Отгрузка",
                desc: "Расходный документ движения товара контрагенту с датой проводки.",
              },
              {
                title: "Действующая ставка",
                desc: "Значение SCD2 на дату: start_date ≤ дата < end_date (текущая — «по» пусто).",
              },
              {
                title: "Активная запись",
                desc: 'Не в архиве (is_active); удаления нет — только архив с аудитом.',
              },
            ].map((item) => (
              <div key={item.title} className="py-2.5">
                <div className="font-semibold text-ink">{item.title}</div>
                <p className="text-[12px] text-muted">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* pgvector (dark) */}
        <div className="rounded-2xl bg-ink p-5 text-slate-300 shadow-card">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <Database className="h-3.5 w-3.5" />
              pgvector — вторично
            </div>
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
              не для точных значений
            </span>
          </div>
          <p className="mt-2 text-[12px] text-slate-400">
            Только нечёткий поиск названий и дедуп похожих записей.
          </p>

          <div className="mt-4 space-y-3 text-sm">
            {[
              {
                title: "Где помогает",
                desc: '«Ромашка» ↔ «ООО Ромашка» ↔ «Romashka» — поиск похожих и склейка дублей в golden record.',
              },
              {
                title: "Границы",
                desc: "При фильтрации (на дату, по статусу) recall падает — вектора не дают точных значений полей.",
              },
              {
                title: "Масштаб",
                desc: "Выделенная vector DB — только при высоком QPS/большом объёме; иначе pgvector в PostgreSQL 16.",
              },
            ].map((item) => (
              <div key={item.title} className="rounded-xl bg-black/30 p-3">
                <div className="font-semibold text-slate-200">{item.title}</div>
                <p className="mt-1 text-[12px] text-slate-400">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Why */}
      <div className="rounded-2xl bg-white p-5 shadow-card">
        <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          <Layers className="h-3.5 w-3.5" />
          Почему так
        </div>
        <p className="text-sm text-slate-700">
          Структурный доступ (SQL/MCP поверх semantic-слоя) даёт{" "}
          <span className="font-semibold">точность</span> и{" "}
          <span className="font-semibold">историчность</span> — значения берутся на дату из
          эталонных записей. Вектора — лишь «похоже на…» для поиска и дедупа. Граф знаний (KG)
          для этого <span className="font-semibold">не обязателен</span>.
        </p>
      </div>
    </div>
  );
}
