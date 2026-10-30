"use client";

import { useInstanceOrganization,withInstanceOrganization } from "@/components/instance-organization-gate";

import clsx from "clsx";
import { Plus,RefreshCw,Search,X } from "lucide-react";
import { useEffect,useMemo,useRef,useState, type KeyboardEvent } from "react";

import { formatNumber } from "@/lib/format";
import {
createSupplier,
emptySupplier,
fetchSuppliers,
fetchSupplierScorecard,
filterSuppliers,
searchSupplierCounterparties,
statusLabel,
updateSupplier,
type Supplier,
type SupplierCounterparty,
type SupplierInput,
type SupplierScorecard,
} from "@/lib/procurement-suppliers";

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-[148px] flex-1 rounded-2xl border border-line bg-surface px-4 py-4 shadow-sm">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink tabular-nums">{value}</div>
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  active: "bg-green-50 text-green-700 dark:bg-green-500/10 dark:text-green-300",
  blocked: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

type Draft = SupplierInput & { id?: number };

function Field({
  label,
  value,
  onChange,
  placeholder,
  readOnly,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  readOnly?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        readOnly={readOnly}
        className="mt-1 min-h-10 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
      />
    </label>
  );
}

 function ProcurementSuppliersTableWorkspace({ initial }: { initial: Supplier[] | null }) {
  const [rows, setRows] = useState<Supplier[]>(initial ?? []);
  const [hasSnapshot, setHasSnapshot] = useState(initial !== null);
  const [listFailed, setListFailed] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [mdmSearch, setMdmSearch] = useState("");
  const [mdmOptions, setMdmOptions] = useState<SupplierCounterparty[]>([]);
  const [mdmError, setMdmError] = useState("");

  const [companyError] = useState("");
  const orgId = String(useInstanceOrganization().id);
  const [scoreSupplierId, setScoreSupplierId] = useState<number | null>(null);
  const [scorecard, setScorecard] = useState<SupplierScorecard | null>(null);
  const [scoreError, setScoreError] = useState("");
  const drawerOpen = draft !== null;
  const drawerRoot = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!drawerOpen) return;
    const opener = document.activeElement;
    closeButton.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected && !opener.closest("[inert]")) opener.focus();
    };
  }, [drawerOpen]);

  function trapDrawer(event: KeyboardEvent<HTMLDivElement>) {
    event.stopPropagation();
    if (event.key === "Escape") { event.preventDefault(); setDraft(null); return; }
    if (event.key !== "Tab") return;
    const controls = [...(drawerRoot.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]'
    ) ?? [])];
    const first = controls[0], last = controls.at(-1);
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === drawerRoot.current)) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  useEffect(() => {
    const term = mdmSearch.trim();
    if (!drawerOpen || term.length < 2) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void searchSupplierCounterparties(term)
        .then(items => { if (active) { setMdmOptions(items); setMdmError(""); } })
        .catch(() => { if (active) { setMdmOptions([]); setMdmError("Справочник контрагентов недоступен"); } });
    }, 250);
    return () => { active = false; window.clearTimeout(timer); };
  }, [drawerOpen, mdmSearch]);

  useEffect(() => {
    void fetchSuppliers().then((d) => {
      if (d !== null) {
        setRows(d); setHasSnapshot(true); setListFailed(false);
      } else setListFailed(true);
    });
  }, []);



  useEffect(() => {
    if (!orgId || scoreSupplierId === null) return;
    let live = true;
    void fetchSupplierScorecard(Number(orgId), scoreSupplierId)
      .then(value => { if (live) setScorecard(value); })
      .catch(() => { if (live) setScoreError("Не удалось получить показатели выбранного юрлица"); });
    return () => { live = false; };
  }, [orgId, scoreSupplierId]);

  async function refresh() {
    setBusy(true);
    setListFailed(false);
    const d = await fetchSuppliers();
    if (d !== null) {
      setRows(d); setHasSnapshot(true);
    } else setListFailed(true);
    setBusy(false);
  }

  const filtered = useMemo(() => filterSuppliers(rows, query), [rows, query]);
  const active = rows.filter((s) => s.status === "active").length;

  function openCreate() {
    setError("");
    setMdmSearch(""); setMdmOptions([]); setMdmError("");
    setDraft({ ...emptySupplier() });
  }
  function openEdit(s: Supplier) {
    setError("");
    setMdmSearch(""); setMdmOptions([]); setMdmError("");
    setDraft({ ...s });
  }

  async function save() {
    if (!draft || !draft.name.trim() || (!draft.id && !draft.counterparty_id)) {
      setError("Выберите поставщика из справочника контрагентов");
      return;
    }
    setSaving(true);
    setError("");
    const { id, ...input } = draft;
    const patch: Partial<SupplierInput> = { ...input };
    const original = rows.find(row => row.id === id);
    if (original?.counterparty_id === input.counterparty_id) delete patch.counterparty_id;
    if (original?.name === input.name) delete patch.name;
    if (original?.unp === input.unp) delete patch.unp;
    const saved = id ? await updateSupplier(id, patch) : await createSupplier(input);
    setSaving(false);
    if (!saved) {
      setError("Не удалось сохранить — попробуйте ещё раз");
      return;
    }
    setDraft(null);
    await refresh();
  }

  return (
    <div className="min-w-0 flex-1 p-4 text-ink [color-scheme:light] dark:[color-scheme:dark] sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-2xl flex-1 basis-72">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted">Закупки · справочник</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">Поставщики</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Профили поставщиков: реквизиты выбираются из MDM по ID; условия оплаты,
          сроки и Incoterms хранятся в закупках. Старые профили без ID требуют сопоставления.
        </p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <button
            onClick={refresh}
            disabled={busy}
            className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
          >
            <RefreshCw size={15} className={clsx(busy && "animate-spin")} /> Обновить
          </button>
          <button
            onClick={openCreate}
            className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            <Plus size={15} /> Добавить
          </button>
        </div>
      </div>

      {listFailed && <div role="alert" className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
        Не удалось загрузить поставщиков. {hasSnapshot ? "Показаны ранее загруженные данные." : "Количество пока не подтверждено."} Повторите загрузку кнопкой «Обновить».
      </div>}

      <div role="region" aria-label="Показатели списка поставщиков" tabIndex={0} className="mt-5 flex gap-3 overflow-x-auto pb-1 outline-none focus-visible:ring-2 focus-visible:ring-accent sm:grid sm:grid-cols-3">
        <Kpi label="Поставщиков" value={hasSnapshot ? formatNumber(rows.length) : "—"} />
        <Kpi label="Активных" value={hasSnapshot ? formatNumber(active) : "—"} />
        <Kpi label="Заблокировано" value={hasSnapshot ? formatNumber(rows.length - active) : "—"} />
      </div>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <span className="text-sm text-muted">Юрлицо задано в настройках.</span>
        <div className="relative w-full sm:ml-auto sm:w-80">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск поставщиков"
            placeholder="Поиск: имя, УНП, страна"
            className="min-h-10 w-full rounded-lg border border-line bg-surface py-2 pl-8 pr-3 text-sm text-ink outline-none focus:border-accent"
          />
        </div>
      </div>
      {companyError && <p role="alert" className="mt-2 text-sm text-red-700">{companyError}</p>}

      <div role="region" aria-label="Список поставщиков" tabIndex={0} className="mt-4 overflow-x-auto rounded-2xl border border-line bg-surface shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <table className="w-full min-w-[920px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Поставщик</th>
              <th className="px-4 py-2 font-medium">Страна</th>
              <th className="px-4 py-2 font-medium">Условия оплаты</th>
              <th className="px-4 py-2 text-right font-medium">Срок, дн</th>
              <th className="px-4 py-2 font-medium">Incoterms</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 font-medium">Показатели</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  {!hasSnapshot ? (listFailed ? "Список поставщиков недоступен" : "Загрузка поставщиков…") : rows.length === 0 ? "Поставщиков пока нет — добавьте первого" : "Ничего не найдено"}
                </td>
              </tr>
            )}
            {filtered.map((s) => (
              <tr
                key={s.id}
                onClick={() => openEdit(s)}
                className="cursor-pointer border-b border-line last:border-0 hover:bg-sunken/50"
              >
                <td className="px-4 py-2.5">
                  <button type="button" aria-label={`Открыть карточку ${s.name}`}
                    onClick={event => { event.stopPropagation(); openEdit(s); }}
                    className="min-h-10 rounded-md text-left font-medium text-ink underline-offset-4 hover:text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{s.name}</button>
                  <div className="text-xs text-muted">{s.counterparty_id ? `MDM ID ${s.counterparty_id} · УНП ${s.unp || "не указан"}` : "Не сопоставлен с MDM"}</div>
                </td>
                <td className="px-4 py-2.5 text-muted">
                  {s.flag} {s.country}
                </td>
                <td className="px-4 py-2.5 text-muted">{s.payment_terms || "—"}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                  {s.lead_time_days ?? "—"}
                </td>
                <td className="px-4 py-2.5 text-muted">{s.incoterms || "—"}</td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      STATUS_TONE[s.status] ?? "bg-sunken text-muted",
                    )}
                  >
                    {statusLabel(s.status)}
                  </span>
                </td>
                <td className="px-4 py-2.5"><button type="button" disabled={!orgId}
                  onClick={event => { event.stopPropagation(); setScoreSupplierId(s.id); setScorecard(null); setScoreError(""); }}
                  className="text-accent underline disabled:text-muted disabled:no-underline">
                  Открыть показатели
                </button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {scoreSupplierId !== null && orgId && <section aria-label="Показатели поставщика" className="mt-4 rounded-xl border border-line bg-surface p-4 text-sm">
        <div className="flex items-center justify-between"><h2 className="font-semibold text-ink">
          Показатели: {rows.find(row => row.id === scoreSupplierId)?.name ?? `ID ${scoreSupplierId}`}
        </h2><button type="button" onClick={() => setScoreSupplierId(null)} aria-label="Закрыть показатели"><X size={18} /></button></div>
        {scoreError && <p role="alert" className="mt-2 text-red-700">{scoreError}</p>}
        {!scoreError && (!scorecard || scorecard.organization_id !== Number(orgId) || scorecard.supplier_id !== scoreSupplierId) && <p className="mt-2 text-muted">Загрузка…</p>}
        {scorecard?.organization_id === Number(orgId) && scorecard.supplier_id === scoreSupplierId && <div className="mt-2 space-y-1">
          <p>Заказов: {scorecard.orders_count}. Поставок с проверяемой датой: {scorecard.on_time_observed_count}; вовремя: {scorecard.on_time_count}.</p>
          <p>Доля своевременных: {scorecard.on_time_rate === null ? "недостаточно данных" : `${Math.round(scorecard.on_time_rate * 100)}%`}.</p>
          <p>Выигранных запросов цен: {scorecard.won_rfq_count}; средняя цена предложения: {scorecard.avg_won_price_byn === null ? "нет данных" : `${scorecard.avg_won_price_byn} BYN`}.</p>
          <p className="text-amber-700">Претензии и общий балл: нет надёжной привязки претензий к юрлицу; показатели предварительные.</p>
        </div>}
      </section>}

      {draft && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/40 backdrop-blur-sm" onClick={() => setDraft(null)} onKeyDown={trapDrawer}>
          <div
            ref={drawerRoot} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="supplier-drawer-title"
            className="flex h-full w-full max-w-lg min-w-0 flex-col bg-canvas text-ink shadow-2xl outline-none"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-4 py-4 sm:px-6">
              <h2 id="supplier-drawer-title" className="text-lg font-semibold text-ink">
                {draft.id ? "Поставщик" : "Новый поставщик"}
              </h2>
              <button ref={closeButton} aria-label="Закрыть карточку поставщика" onClick={() => setDraft(null)} className="flex h-10 w-10 items-center justify-center rounded-lg border border-line text-muted hover:bg-sunken hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                <X size={18} />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
            <div className="grid grid-cols-1 gap-4">
              {!rows.find(row => row.id === draft.id)?.counterparty_id && <>
                <label className="block text-sm">Поиск контрагента MDM
                  <input aria-label="Поиск контрагента MDM" value={mdmSearch} onChange={event => {
                    setMdmSearch(event.target.value); setMdmOptions([]); setMdmError("");
                    const original = rows.find(row => row.id === draft.id);
                    setDraft({ ...draft, counterparty_id: null, name: original?.name ?? "", unp: original?.unp ?? "" });
                  }} className="mt-1 min-h-10 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2" />
                </label>
                <label className="block text-sm">Поставщик из справочника
                  <select aria-label="Поставщик из справочника" value={draft.counterparty_id ?? ""}
                    onChange={event => {
                      const selected = mdmOptions.find(row => row.id === Number(event.target.value));
                      if (selected) setDraft({ ...draft, counterparty_id: selected.id, name: selected.name, unp: selected.unp });
                    }} className="mt-1 min-h-10 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2">
                    <option value="">Выберите контрагента</option>
                    {draft.counterparty_id && !mdmOptions.some(row => row.id === draft.counterparty_id) &&
                      <option value={draft.counterparty_id}>{draft.name} · {draft.unp || "без УНП"} · ID {draft.counterparty_id}</option>}
                    {mdmOptions.map(row => <option key={row.id} value={row.id}>{row.name} · {row.unp || "без УНП"} · ID {row.id}</option>)}
                  </select>
                </label>
                {mdmError && <p role="alert" className="text-red-600">{mdmError}</p>}
              </>}
              {draft.id && !draft.counterparty_id && <p className="text-xs text-amber-700">Исторический профиль не сопоставлен; существующие реквизиты нельзя считать подтверждёнными MDM.</p>}
              <Field label="Название" value={draft.name} onChange={() => {}} readOnly />
              <div className="grid grid-cols-1 gap-4 min-[360px]:grid-cols-2">
                <Field label="УНП (MDM)" value={draft.unp} onChange={() => {}} readOnly />
                <Field label="Страна" value={draft.country} onChange={(v) => setDraft({ ...draft, country: v })} />
              </div>
              <div className="grid grid-cols-1 gap-4 min-[360px]:grid-cols-2">
                <Field label="Флаг (emoji)" value={draft.flag} onChange={(v) => setDraft({ ...draft, flag: v })} />
                <Field label="Incoterms" value={draft.incoterms} onChange={(v) => setDraft({ ...draft, incoterms: v })} />
              </div>
              <Field label="Контактное лицо" value={draft.contact_person} onChange={(v) => setDraft({ ...draft, contact_person: v })} />
              <div className="grid grid-cols-1 gap-4 min-[360px]:grid-cols-2">
                <Field label="Телефон" value={draft.phone} onChange={(v) => setDraft({ ...draft, phone: v })} />
                <Field label="Email" value={draft.email} onChange={(v) => setDraft({ ...draft, email: v })} />
              </div>
              <Field
                label="Условия оплаты"
                value={draft.payment_terms}
                onChange={(v) => setDraft({ ...draft, payment_terms: v })}
                placeholder="30% предоплата / 70% по факту"
              />
              <div className="grid grid-cols-1 gap-4 min-[360px]:grid-cols-2">
                <Field
                  label="Срок поставки, дн"
                  value={draft.lead_time_days == null ? "" : String(draft.lead_time_days)}
                  onChange={(v) =>
                    setDraft({ ...draft, lead_time_days: v.trim() === "" ? null : Number(v) || 0 })
                  }
                />
                <label className="block">
                  <span className="text-xs font-medium text-muted">Статус</span>
                  <select
                    value={draft.status}
                    onChange={(e) => setDraft({ ...draft, status: e.target.value })}
                    className="mt-1 min-h-10 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                  >
                    <option value="active">Активен</option>
                    <option value="blocked">Заблокирован</option>
                  </select>
                </label>
              </div>
              <Field label="Заметки" value={draft.notes} onChange={(v) => setDraft({ ...draft, notes: v })} />
            </div>

            {error && <div className="mt-3 text-sm text-red-600">{error}</div>}

            </div>
            <div className="flex shrink-0 gap-2 border-t border-line bg-surface px-4 py-4 sm:px-6">
              <button
                onClick={save}
                disabled={saving}
                className="min-h-10 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
              >
                {saving ? "Сохранение…" : "Сохранить"}
              </button>
              <button
                onClick={() => setDraft(null)}
                className="min-h-10 rounded-lg border border-line bg-surface px-4 py-2 text-sm font-medium text-muted hover:bg-sunken"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export const ProcurementSuppliersTable = withInstanceOrganization(ProcurementSuppliersTableWorkspace);
