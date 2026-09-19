"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AccountingReopening } from "./accounting-reopening";
import { AccountingClosingHistory } from "./accounting-closing-history";
import { AccountingClosingPreview } from "./accounting-closing-preview";
import { AccountingClosingControls } from "./accounting-closing-controls";
import { AccountingSourceLink } from "./accounting-source-link";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { FinancialClosingPolicyFields, type ClosingSelection } from "./financial-closing-policy-fields";
import { ProductionCostPolicyFields, type ProductionCostSelection } from "./production-cost-policy-fields";
import { AccountingProductionCostSources } from "./accounting-production-cost-sources";
import { FxPolicyFields, type FxPolicySelection } from "./fx-policy-fields";

type Period = { month: string; generation: number; closed: boolean };
type SourceControl = { id: number; source: string; version: number; month: string };
type PendingLine = { account: string; side: string; amount: string; dimensions?: Record<string, string>; currency?: string; original_amount?: string | null; rate?: string | null; rate_scale?: number | null; rate_date?: string | null; rate_source?: string | null; quantity?: string | null };
type Pending = { id: number; event_key: string; month: string; error: string | null; payload: { source?: string; source_version?: number; operation?: string; document_date?: string; operation_date?: string; posting_date?: string; policy_id?: number; rule_version?: string; explanation?: string; lines?: PendingLine[] } };
type Catalog = { version: string; accounts: { code: string; title: string }[] };
type ImportControlTotals = { entry_count: number; line_count: number; debit_byn: string; credit_byn: string };
type ImportPreview = { batch: string; request_key: string; cutover_date: string; source_system: string; source_digest: string; command_digest: string; control_totals: ImportControlTotals; confirmed: boolean; already_confirmed?: boolean };
type ImportReceipt = ImportPreview & { receipt_id: number; entry_ids: number[]; evidence: string; digest: string; created_at: string };
const steps: Record<string, string> = { documents: "Полнота документов", bank: "Сверка банка", settlements: "Сверка расчётов", stock: "Сверка склада", costing: "Себестоимость и затраты", depreciation: "Амортизация", fx: "Валютные операции", tax: "Налоги", financial_result: "Финансовый результат", trial_balance: "Контрольная ОСВ" };
const dimensions: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", employee: "Сотрудник", asset: "Основное средство", department: "Подразделение", owner: "Владелец", serial: "Серийный номер" };

async function api<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, { method: body === undefined ? "GET" : method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте обязательные поля и права доступа.");
  return data as T;
}

async function sha256Hex(value: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", value);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

export function AccountingControls({ org, onChanged, initialSection = "setup", onBusyChange, onShipment, onEntry }: { org: string; onChanged: () => void; initialSection?: string; onBusyChange?: (busy: boolean) => void; onShipment?: (source: string) => void; onEntry?: (id: number) => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [section, setSection] = useState(initialSection);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [closingBusy, setClosingBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [periods, setPeriods] = useState<Period[]>([]);
  const [inbox, setInbox] = useState<Pending[]>([]);
  const [sources, setSources] = useState<SourceControl[]>([]);
  const [selected, setSelected] = useState<Pending | null>(null);
  const [month, setMonth] = useState(today.slice(0, 7));
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [unp, setUnp] = useState("");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [account, setAccount] = useState({ code: "", title: "", category: "", valid_from: today, normative_ref: "", required_dimensions: [] as string[], cash: false, currency_tracking: false, quantity_tracking: false });
  const [policy, setPolicy] = useState({ effective_from: today, reference: "", inventory_method: "", allocation_basis: "", depreciation_method: "", normative_reference: "", normative_verified: false });
  const [closing, setClosing] = useState<ClosingSelection | null>(null);
  const [production, setProduction] = useState<ProductionCostSelection | null>(null);
  const [fx, setFx] = useState<FxPolicySelection | null>(null);
  const [closingIntent, setClosingIntent] = useState({ org, enabled: false });
  const closingEnabled = closingIntent.org === org && closingIntent.enabled;
  const closingScope = `${org}:${policy.effective_from}`;
  const fxReady = fx?.scope === closingScope && (!fx.enabled || fx.value !== null);
  const productionReady = production?.scope === closingScope && (!production.enabled || production.value !== null);
  const [lateCost, setLateCost] = useState({ scope: "", enabled: false, basis: "", rounding: "" });
  const late = lateCost.scope === closingScope ? lateCost : { scope: closingScope, enabled: false, basis: "", rounding: "" };
  const lateReady = !late.enabled || Boolean(late.basis && late.rounding);
  const closingReady = closing?.scope === closingScope && closing.enabled === closingEnabled && (!closing.enabled || closing.value !== null);
  const saveLock = useRef(false);
  const [member, setMember] = useState({ subject: "", role: "reader" });
  const [importData, setImportData] = useState<unknown>(null);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importReceipts, setImportReceipts] = useState<ImportReceipt[]>([]);
  const prefix = `/organizations/${org}`;
  const mounted = useRef(true);
  const onChangedRef = useRef(onChanged);
  useLayoutEffect(() => { onChangedRef.current = onChanged; }, [onChanged]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    let active = true;
    void api<Catalog>("/catalog").then((data) => { if (active) setCatalog(data); }).catch(() => { /* Working accounts remain available when reference catalogue is offline. */ });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!org) return;
    let active = true;
    void Promise.all([api<Period[]>(`${prefix}/periods`), api<Pending[]>(`${prefix}/inbox`), api<SourceControl[]>(`${prefix}/source-controls`)])
      .then(([p, i, s]) => { if (active) { setPeriods(p); setInbox(i); setSources(s); } })
      .catch((e: Error) => { if (active) setError(e.message); });
    void api<ImportReceipt[]>(`${prefix}/imports`).then((rows) => { if (active) setImportReceipts(rows); }).catch(() => { if (active) setImportReceipts([]); });
    return () => { active = false; };
  }, [org, prefix, refresh]);

  async function save(path: string, body: unknown, message: string, method = "POST") {
    if (saveLock.current || closingBusy) return;
    saveLock.current = true;
    onBusyChange?.(true);
    setBusy(true); setError(""); setNotice("");
    try { await api(path, body, method); if (!mounted.current) return; setNotice(message); setRefresh((v) => v + 1); setSelected(null); setImportPreview(null); setEvidence({}); onChangedRef.current(); }
    catch (e) { setError((e as Error).message); }
    finally { saveLock.current = false; setBusy(false); onBusyChange?.(false); }
  }
  function savePolicy() {
    if (!fxReady) { setError("Проверьте настройки валютного учёта для выбранной организации и даты."); return; }
    if (production?.scope !== closingScope || (production.enabled && !production.value)) { setError("Проверьте настройки производственных затрат."); return; }
    if (!lateReady) { setError("Выберите базу и правило округления поздних расходов."); return; }
    if (!closingReady || closing?.scope !== `${org}:${policy.effective_from}`) { setError("Проверьте настройки переноса для выбранной организации и даты политики."); return; }
    void save(`${prefix}/policies`, { ...policy, ...(closing.enabled ? { financial_closing: closing.value } : {}),
      ...(fx?.enabled ? { currency_revaluation: fx.value } : {}),
      ...(late.enabled ? { late_cost_allocation: { basis: late.basis, rounding: late.rounding } } : {}),
      ...(production.enabled ? { production_costing: production.value } : {}) }, "Версия политики сохранена.");
  }
  async function readImport(file: File | undefined) {
    setImportData(null); setImportPreview(null); setError("");
    if (!file) return;
    if (file.size > 5_000_000) { setError("Файл превышает 5 МБ. Разделите остатки на пакеты."); return; }
    setBusy(true);
    try {
      const raw = await file.arrayBuffer();
      const parsed: unknown = JSON.parse(new TextDecoder().decode(raw));
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Файл должен содержать JSON-пакет остатков.");
      const sourceDigest = typeof (parsed as Record<string, unknown>).source_digest === "string"
        ? (parsed as Record<string, unknown>).source_digest
        : await sha256Hex(raw);
      const body = { ...(parsed as Record<string, unknown>), source_digest: sourceDigest };
      const checked = await api<ImportPreview>(`${prefix}/imports/preview`, body);
      setImportData(body); setImportPreview(checked);
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const current = periods.find((p) => p.month === month);

  return <section className="min-w-0 space-y-4 rounded-xl border border-line bg-surface p-2 sm:p-4 [&_button]:max-w-full [&_button]:whitespace-normal">
    <nav className="flex flex-wrap gap-2" aria-label="Управление книгой">{[["setup", "Настройки книги"], ["periods", "Закрытие месяца"], ["inbox", "Не проведено"], ["import", "Импорт остатков"]].map(([id, title]) => <Button key={id} disabled={busy || closingBusy} variant={section === id ? "primary" : "secondary"} onClick={() => { setSection(id); setError(""); setNotice(""); }}>{title}</Button>)}</nav>
    {error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p role="status" className="text-money">{notice}</p>}
    <fieldset disabled={busy} className="min-w-0 space-y-5">
      <div hidden={section !== "setup"} className="space-y-5">
        <div className="space-y-2"><h2 className="font-semibold">Новая организация</h2><p className="text-sm text-muted">Создаёт руководитель. Доступ к новой книге получает только создатель.</p><div className="grid gap-3 md:grid-cols-3"><Input aria-label="Название организации" placeholder="Полное наименование" value={name} onChange={(e) => setName(e.target.value)} /><Input aria-label="УНП" placeholder="УНП — 9 цифр" value={unp} onChange={(e) => setUnp(e.target.value)} /><Button disabled={!name || !/^\d{9}$/.test(unp)} onClick={() => void save("/organizations", { name, unp }, "Организация создана. Выберите её в списке книг.")}>Создать организацию</Button></div></div>
        {org && <>
          <div className="space-y-3 border-t border-line pt-4"><h2 className="font-semibold">Версия рабочего счёта</h2><p className="text-sm text-muted">Справочник служит основой для выбора. Актуальность нормативной редакции и настройки утверждает бухгалтер.</p>
            {catalog && <Select aria-label="Счёт из справочника" value="" onChange={(e) => { const found = catalog.accounts.find((a) => a.code === e.target.value); if (found) setAccount({ ...account, code: found.code, title: found.title }); }}><option value="">Выбрать из справочника</option>{catalog.accounts.map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select>}
            <div className="grid gap-3 md:grid-cols-3"><Input aria-label="Код нового счёта" placeholder="Код счёта" value={account.code} onChange={(e) => setAccount({ ...account, code: e.target.value })} /><Input aria-label="Название счёта" placeholder="Название" value={account.title} onChange={(e) => setAccount({ ...account, title: e.target.value })} /><Select aria-label="Категория счёта" value={account.category} onChange={(e) => setAccount({ ...account, category: e.target.value })}><option value="">Категория для отчётов</option>{[["asset", "Актив"], ["liability", "Обязательство"], ["equity", "Капитал"], ["income", "Доход"], ["expense", "Расход"], ["off_balance", "Забалансовый"]].map(([v, label]) => <option key={v} value={v}>{label}</option>)}</Select><label className="text-sm">Действует с<Input type="date" value={account.valid_from} onChange={(e) => setAccount({ ...account, valid_from: e.target.value })} /></label><Input aria-label="Основание рабочего счёта" placeholder="Основание / пункт учётной политики" value={account.normative_ref} onChange={(e) => setAccount({ ...account, normative_ref: e.target.value })} /></div>
            <div className="flex flex-wrap gap-3">{Object.entries(dimensions).map(([key, label]) => <label key={key} className="text-sm"><input type="checkbox" checked={account.required_dimensions.includes(key)} onChange={(e) => setAccount({ ...account, required_dimensions: e.target.checked ? [...account.required_dimensions, key] : account.required_dimensions.filter((d) => d !== key) })} /> {label}</label>)}</div>
            <div className="flex flex-wrap gap-4">{([["cash", "Денежный счёт"], ["currency_tracking", "Валютный учёт"], ["quantity_tracking", "Количественный учёт"]] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={account[key]} onChange={(e) => setAccount({ ...account, [key]: e.target.checked })} /> {label}</label>)}</div><Button disabled={!account.code || !account.title || !account.category || !account.normative_ref} onClick={() => void save(`${prefix}/accounts`, account, "Версия счёта сохранена.")}>Сохранить версию счёта</Button>
          </div>
          <div className="space-y-3 border-t border-line pt-4"><h2 className="font-semibold">Учётная политика</h2><div className="grid gap-3 md:grid-cols-2"><label>Действует с<Input type="date" value={policy.effective_from} onChange={(e) => setPolicy({ ...policy, effective_from: e.target.value })} /></label><Input aria-label="Приказ об учётной политике" placeholder="Приказ / версия политики" value={policy.reference} onChange={(e) => setPolicy({ ...policy, reference: e.target.value })} />
            <Select aria-label="Метод оценки запасов" value={policy.inventory_method} onChange={(e) => setPolicy({ ...policy, inventory_method: e.target.value })}><option value="">Метод оценки запасов</option><option value="fifo">ФИФО</option><option value="weighted_average">Средневзвешенная стоимость</option><option value="specific">Стоимость отдельной единицы</option></Select>
            <Select aria-label="База распределения" value={policy.allocation_basis} onChange={(e) => setPolicy({ ...policy, allocation_basis: e.target.value })}><option value="">База распределения затрат</option><option value="direct_cost">Прямые затраты</option><option value="labor_hours">Трудозатраты</option><option value="output_quantity">Количество выпуска</option></Select>
            <Select aria-label="Метод амортизации" value={policy.depreciation_method} onChange={(e) => setPolicy({ ...policy, depreciation_method: e.target.value })}><option value="">Метод амортизации</option><option value="straight_line">Линейный</option><option value="declining_balance">Уменьшаемого остатка</option><option value="production_units">Производительный</option></Select><Input aria-label="Проверенная нормативная база" placeholder="Редакция и основание нормативной проверки" value={policy.normative_reference} onChange={(e) => setPolicy({ ...policy, normative_reference: e.target.value })} /></div>
            <FinancialClosingPolicyFields org={org} effectiveDate={policy.effective_from} enabled={closingEnabled} onEnabledChange={enabled => setClosingIntent({ org, enabled })} onChange={setClosing} />
            <ProductionCostPolicyFields org={org} effectiveDate={policy.effective_from} onChange={setProduction} />
            <FxPolicyFields key={closingScope} org={org} effectiveDate={policy.effective_from} onChange={setFx} />
            <fieldset className="min-w-0 space-y-2 rounded-lg border border-line p-3">
              <legend>Поздние дополнительные расходы</legend>
              <label className="block text-sm"><input type="checkbox" checked={late.enabled} onChange={event => setLateCost({ ...late, enabled: event.target.checked })} /> Настроить распределение поздних расходов</label>
              {late.enabled && <>
                <label className="block text-sm">База поздних расходов<Select value={late.basis} onChange={event => setLateCost({ ...late, basis: event.target.value })}>
                  <option value="">Выберите базу</option><option value="quantity">Количество поступившего товара</option><option value="received_value">Стоимость поступившего товара</option>
                </Select></label>
                <label className="block text-sm">Округление поздних расходов<Select value={late.rounding} onChange={event => setLateCost({ ...late, rounding: event.target.value })}>
                  <option value="">Выберите правило</option><option value="largest_remainder_cent">По наибольшим остаткам до копейки</option>
                </Select></label>
                <p className="text-sm text-muted">Укажите метод действующей учётной политики. Предварительный расчёт пока поддерживает идентификацию отдельной партии. Эти настройки сохраняются только в новой версии политики.</p>
              </>}
            </fieldset>
            <label className="block text-sm"><input type="checkbox" checked={policy.normative_verified} onChange={(e) => setPolicy({ ...policy, normative_verified: e.target.checked })} /> Бухгалтер проверил применимую нормативную редакцию</label><Button disabled={!fxReady || !productionReady || !lateReady || !closingReady || !policy.reference || !policy.inventory_method || !policy.allocation_basis || !policy.depreciation_method || !policy.normative_reference} onClick={savePolicy}>Утвердить версию политики</Button>
          </div>
          <div className="space-y-2 border-t border-line pt-4"><h2 className="font-semibold">Доступ к книге</h2><Input aria-label="Идентификатор сотрудника" placeholder="Идентификатор сотрудника в системе входа" value={member.subject} onChange={(e) => setMember({ ...member, subject: e.target.value })} /><Select aria-label="Права сотрудника" value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value })}><option value="reader">Просмотр</option><option value="accountant">Бухгалтер</option><option value="chief">Главный бухгалтер</option></Select><Button disabled={!member.subject} onClick={() => void save(`${prefix}/members`, member, "Доступ сохранён.", "PUT")}>Назначить доступ</Button></div>
        </>}
      </div>
      {section === "periods" && org && <div className="space-y-3"><AccountingClosingHistory key={`history:${org}:${month}:${refresh}`} org={org} month={month} onEntry={onEntry} /><AccountingClosingPreview key={`${org}:${month}:${refresh}`} org={org} month={month} evidence={evidence} onLock={value => { setClosingBusy(value); onBusyChange?.(value); }} onClosed={(_id, currentlyClosed) => { setNotice(currentlyClosed ? "Месяц закрыт с переносом финансового результата." : "Закрытие ранее выполнено; сейчас месяц открыт для исправлений."); setEvidence({}); setRefresh(value => value + 1); onChangedRef.current(); }} /><AccountingClosingControls org={org} month={month} disabled={busy || closingBusy} /><h2 className="font-semibold">Контроль и блокировка месяца</h2><p className="text-sm text-muted">Здесь фиксируются результаты выполненных проверок. Перенос финансового результата рассчитывается по учётной политике. Налоги и себестоимость должны быть проверены отдельно.</p><Input disabled={closingBusy} aria-label="Месяц закрытия" type="month" value={month} onChange={(e) => { setMonth(e.target.value); setEvidence({}); }} /><p>{current?.closed ? "Месяц закрыт" : "Месяц открыт"}</p>{!current?.closed && <>{Object.entries(steps).map(([key, label]) => <label className="block text-sm" key={key}>{label}<Input disabled={closingBusy} aria-label={label} value={evidence[key] || ""} placeholder="Протокол сверки / документ с результатом проверки" onChange={(e) => setEvidence({ ...evidence, [key]: e.target.value })} /></label>)}<Button disabled={closingBusy || Object.keys(steps).some((k) => !evidence[k]?.trim())} onClick={() => void save(`${prefix}/periods/${month}/close`, { expected_generation: current?.generation ?? 0, evidence }, "Месяц заблокирован.")}>Подтвердить проверки и закрыть</Button></>}{current?.closed && <AccountingReopening key={`reopen:${org}:${month}:${refresh}`} org={org} month={month} onLock={value => { setClosingBusy(value); onBusyChange?.(value); }} onReopened={currentlyOpen => { setNotice(currentlyOpen ? "Периоды открыты для исправлений. Повторите контрольные проверки." : "Открытие ранее выполнено; часть периодов уже закрыта повторно."); setEvidence({}); setRefresh(value => value + 1); onChangedRef.current(); }} />}</div>}
      {section === "periods" && org && <AccountingProductionCostSources org={org} month={month} disabled={busy || closingBusy} onEntry={onEntry}
        onLock={value => { setClosingBusy(value); onBusyChange?.(value); }}
        onChanged={() => { setEvidence({}); setRefresh(value => value + 1); onChangedRef.current(); }} />}
      {section === "inbox" && org && <div className="space-y-3"><h2 className="font-semibold">Документы, ожидающие проведения</h2>{inbox.map((row) => <div key={row.id} className="border-b border-line pb-3"><Button variant="secondary" onClick={() => setSelected(row)}>{row.event_key} · {row.month}</Button><p className="mt-2 text-sm text-red-700">{row.error || "Ожидает проверки бухгалтером"}</p></div>)}{sources.map((row) => <div key={`source:${row.id}`}>{row.source} · версия {row.version} · {row.month} · <AccountingSourceLink org={org} source={row.source} onPosted={() => { setNotice("Поступление проведено. Очередь и отчёты обновляются."); setRefresh(v => v + 1); onChangedRef.current(); }} />{onShipment && row.source.startsWith(`wms:physical-shipment:${org}:`) && <Button variant="secondary" onClick={() => onShipment(row.source)}>Подготовить проводки отгрузки</Button>}</div>)}{!inbox.length && !sources.length && <p>Нет ожидающих документов.</p>}{selected && <div className="rounded-xl border border-accent p-3"><h3>{selected.payload.explanation || selected.event_key}</h3><dl className="grid gap-1 text-sm text-muted sm:grid-cols-2"><div><dt className="inline font-semibold">Источник: </dt><dd className="inline">{selected.payload.source || selected.event_key} · версия {selected.payload.source_version ?? "—"}</dd></div><div><dt className="inline font-semibold">Операция: </dt><dd className="inline">{selected.payload.operation || "—"} · правило {selected.payload.rule_version || "—"}</dd></div><div><dt className="inline font-semibold">Даты: </dt><dd className="inline">документ {selected.payload.document_date || "—"} · операция {selected.payload.operation_date || "—"} · отражение {selected.payload.posting_date || "—"}</dd></div><div><dt className="inline font-semibold">Политика: </dt><dd className="inline">{selected.payload.policy_id ?? "—"}</dd></div></dl>{selected.payload.lines?.map((line, i) => <article key={i} className="mt-3 rounded border border-line p-2"><p>{line.side === "debit" ? "Дт" : "Кт"} {line.account} — {line.amount} {line.currency || "BYN"}{line.quantity ? ` · количество ${line.quantity}` : ""}</p>{line.dimensions && Object.keys(line.dimensions).length > 0 && <p className="text-sm text-muted">Аналитика: {Object.entries(line.dimensions).map(([key, value]) => `${key}=${value}`).join(" · ")}</p>}{line.currency && line.currency !== "BYN" && <p className="text-sm text-muted">Исходная сумма: {line.original_amount || "—"} {line.currency}; курс {line.rate || "—"}, масштаб {line.rate_scale ?? "—"}, дата {line.rate_date || "—"}, источник {line.rate_source || "—"}</p>}</article>)}<Button onClick={() => void save(`${prefix}/inbox/${selected.id}/confirm`, {}, "Документ проверен и проведён.")}>Подтвердить пакет и повторить проведение</Button></div>}</div>}
      {section === "import" && org && <div className="space-y-3"><h2 className="font-semibold">Ввод начальных остатков</h2><p className="text-sm text-muted">Загрузите JSON-пакет opening-balance-v1 с request_key, датой среза, источником, хэшем файла, контрольными суммами и протоколом сверки. Сначала выполняется preview; подтверждение создаёт одну неизменяемую квитанцию и связанные проводки атомарно.</p><Input aria-label="Файл остатков" type="file" accept=".json,application/json" onChange={(e) => void readImport(e.target.files?.[0])} />{importPreview && <div className="space-y-2 rounded-lg border border-line p-3"><p>Пакет: {importPreview.batch} · срез {importPreview.cutover_date} · источник {importPreview.source_system}.</p><p>Операций: {importPreview.control_totals.entry_count}, строк: {importPreview.control_totals.line_count}; Дт {importPreview.control_totals.debit_byn} BYN = Кт {importPreview.control_totals.credit_byn} BYN.</p><p className="break-all text-sm text-muted">Хэш источника: {importPreview.source_digest}<br />Хэш пакета: {importPreview.command_digest}</p>{importPreview.already_confirmed ? <p role="status">Этот пакет уже подтверждён; повторная отправка не создаст новые проводки.</p> : <Button onClick={() => void save(`${prefix}/imports/confirm`, importData, "Остатки перенесены. Сверьте ОСВ с протоколом квитанции.")}>Подтвердить перенос остатков</Button>}</div>}{importReceipts.length > 0 && <div className="space-y-2 border-t border-line pt-3"><h3 className="font-semibold">Протоколы переноса</h3>{importReceipts.map((receipt) => <div key={receipt.receipt_id} className="rounded-lg border border-line p-2 text-sm"><p>{receipt.batch} · {receipt.cutover_date} · {receipt.source_system}</p><p>Дт {receipt.control_totals.debit_byn} BYN = Кт {receipt.control_totals.credit_byn} BYN · проводок: {receipt.entry_ids.length}</p><p className="break-all text-muted">Квитанция {receipt.receipt_id} · {receipt.digest}</p></div>)}</div>}</div>}
    </fieldset>
  </section>;
}
