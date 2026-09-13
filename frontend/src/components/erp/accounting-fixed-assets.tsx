"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Asset = { id: number; asset_key: string; name: string; inventory_number: string; source_entry_id: number; source_line_id: number; digest: string; commissioning_date: string; depreciation_start: string; cost: string; residual_value: string; useful_life_months: number; depreciation_method: string; asset_account: string; accumulated_account: string; expense_account: string; dimensions: Record<string, string> };
type Props = { org: string; month: string; policyId: string; onEntry: (id: number) => void; disabled?: boolean };
type Preview = { digest: string; register_available: boolean; status: string; statutory_certified: false };
type DepPreview = { digest: string; posting_available: boolean; status: string; calculation?: { amount: string; remaining_value: string }; statutory_certified: false; final_cost_certified: false };
const requestKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0")}`;

export function AccountingFixedAssets({ org, month, policyId, onEntry, disabled = false }: Props) {
  const [rows, setRows] = useState<Asset[]>([]), [rowsOrg, setRowsOrg] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState(""), [reload, setReload] = useState(0);
  const [sourceEntry, setSourceEntry] = useState(""), [sourceLine, setSourceLine] = useState(""), [sourceDigest, setSourceDigest] = useState("");
  const [assetKey, setAssetKey] = useState("asset:"), [name, setName] = useState(""), [inventoryNumber, setInventoryNumber] = useState("");
  const [acquisitionDate, setAcquisitionDate] = useState(`${month}-01`), [commissioningDate, setCommissioningDate] = useState(`${month}-01`), [depreciationStart, setDepreciationStart] = useState(`${month}-01`);
  const [cost, setCost] = useState(""), [residual, setResidual] = useState("0.00"), [life, setLife] = useState("12"), [department, setDepartment] = useState("");
  const [assetAccount, setAssetAccount] = useState("01.1"), [accumulatedAccount, setAccumulatedAccount] = useState("02.1"), [expenseAccount, setExpenseAccount] = useState("26"), [evidence, setEvidence] = useState("");
  const [registerKey, setRegisterKey] = useState(requestKey), [registerPreview, setRegisterPreview] = useState<Preview | null>(null), [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!org) return;
    let active = true;
    fetch(`/api/accounting/organizations/${org}/fixed-assets`, { cache: "no-store" }).then(async response => {
      if (!response.ok) throw new Error("Не удалось загрузить реестр ОС.");
      const data = await response.json();
      if (active) { setRows(Array.isArray(data.rows) ? data.rows : []); setRowsOrg(org); }
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "Не удалось загрузить реестр ОС."); });
    return () => { active = false; };
  }, [org, reload]);
  function registrationCommand() {
    return { request_key: registerKey, asset_key: assetKey.trim(), source_entry_id: Number(sourceEntry), source_line_id: Number(sourceLine), expected_source_digest: sourceDigest.trim(), name: name.trim(), inventory_number: inventoryNumber.trim(), acquisition_date: acquisitionDate, commissioning_date: commissioningDate, depreciation_start: depreciationStart, cost: cost.trim(), residual_value: residual.trim(), useful_life_months: Number(life), depreciation_method: "straight_line", asset_account: assetAccount.trim(), accumulated_account: accumulatedAccount.trim(), expense_account: expenseAccount.trim(), dimensions: department.trim() ? { department: department.trim() } : {}, evidence: evidence.trim() };
  }
  async function previewRegister() {
    const command = registrationCommand();
    if (!command.asset_key || !Number.isInteger(command.source_entry_id) || command.source_entry_id <= 0 || !Number.isInteger(command.source_line_id) || command.source_line_id <= 0 || !/^[a-f0-9]{64}$/.test(command.expected_source_digest) || !command.name || !command.inventory_number || !/^\d+\.\d{2}$/.test(command.cost) || !/^\d+\.\d{2}$/.test(command.residual_value) || !Number.isInteger(command.useful_life_months) || command.useful_life_months <= 0 || command.evidence.length < 10) { setError("Укажите источник, digest, инвентарный номер, стоимость, срок и доказательство регистрации ОС."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/fixed-assets/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(command) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Регистрация ОС не подготовлена.");
      if (String(data.organization_id) !== org || data.status !== "reviewed_fixed_asset" || data.register_available !== true || data.statutory_certified !== false || typeof data.digest !== "string") throw new Error("Ответ проверки не соответствует выбранной ОС.");
      setRegisterPreview(data as Preview); setNotice("Пакет регистрации ОС проверен. Запись ещё не сохранена.");
    } catch (e) { setError(e instanceof Error ? e.message : "Регистрация ОС не подготовлена."); }
    finally { setBusy(false); }
  }
  async function confirmRegister() {
    if (!registerPreview || busy) return;
    setBusy(true); setError("");
    try {
      const accessResponse = await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
      const access = await accessResponse.json();
      if (!accessResponse.ok || String(access?.organization_id) !== org || typeof access.principal !== "string" || access.can_confirm !== true) throw new Error("Нет права регистрировать ОС.");
      const response = await fetch(`/api/accounting/organizations/${org}/fixed-assets/confirm`, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": access.principal }, cache: "no-store", body: JSON.stringify({ ...registrationCommand(), digest: registerPreview.digest }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Реестр ОС не сохранён.");
      if (String(data.organization_id) !== org || data.digest !== registerPreview.digest) throw new Error("Ответ сохранения ОС не соответствует пакету.");
      setNotice("ОС зарегистрировано. Налоговая амортизация автоматически не сертифицирована."); setRegisterPreview(null); setRegisterKey(requestKey()); setReload(value => value + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "Реестр ОС не сохранён."); }
    finally { setBusy(false); }
  }
  const visibleRows = rowsOrg === org ? rows : [];
  return <section aria-label="Основные средства и амортизация" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">Основные средства и амортизация</h2><Button variant="secondary" disabled={disabled || busy || !org} onClick={() => setReload(value => value + 1)}>Обновить реестр</Button></div>
    <p className="text-sm text-muted">Регистрация ОС начинается с проведённой строки 01. Укажите источник и правила вручную. В пилоте рассчитывается только straight-line; нормативная и налоговая сертификация не создаётся автоматически.</p>
    <section className="space-y-2 rounded border border-line p-3"><h3 className="font-semibold">Зарегистрировать ОС по проводке</h3>
      <div className="grid gap-2 md:grid-cols-3"><Input aria-label="ID проводки приобретения ОС" value={sourceEntry} disabled={disabled || busy || !!registerPreview} onChange={e => setSourceEntry(e.target.value)} placeholder="Entry ID" /><Input aria-label="ID строки приобретения ОС" value={sourceLine} disabled={disabled || busy || !!registerPreview} onChange={e => setSourceLine(e.target.value)} placeholder="Line ID" /><Input aria-label="Digest проводки приобретения ОС" value={sourceDigest} disabled={disabled || busy || !!registerPreview} onChange={e => setSourceDigest(e.target.value)} placeholder="SHA-256" />
        <Input aria-label="Ключ ОС" value={assetKey} disabled={disabled || busy || !!registerPreview} onChange={e => setAssetKey(e.target.value)} /><Input aria-label="Наименование ОС" value={name} disabled={disabled || busy || !!registerPreview} onChange={e => setName(e.target.value)} placeholder="Наименование" /><Input aria-label="Инвентарный номер ОС" value={inventoryNumber} disabled={disabled || busy || !!registerPreview} onChange={e => setInventoryNumber(e.target.value)} placeholder="Инвентарный номер" />
        <Input aria-label="Дата приобретения ОС" type="date" value={acquisitionDate} disabled={disabled || busy || !!registerPreview} onChange={e => setAcquisitionDate(e.target.value)} /><Input aria-label="Дата ввода ОС" type="date" value={commissioningDate} disabled={disabled || busy || !!registerPreview} onChange={e => setCommissioningDate(e.target.value)} /><Input aria-label="Дата начала амортизации ОС" type="date" value={depreciationStart} disabled={disabled || busy || !!registerPreview} onChange={e => setDepreciationStart(e.target.value)} />
        <Input aria-label="Стоимость ОС" value={cost} disabled={disabled || busy || !!registerPreview} onChange={e => setCost(e.target.value)} placeholder="0.00 BYN" /><Input aria-label="Ликвидационная стоимость ОС" value={residual} disabled={disabled || busy || !!registerPreview} onChange={e => setResidual(e.target.value)} /><Input aria-label="Срок амортизации ОС" value={life} disabled={disabled || busy || !!registerPreview} onChange={e => setLife(e.target.value)} placeholder="Месяцы" />
        <Input aria-label="Счёт ОС" value={assetAccount} disabled={disabled || busy || !!registerPreview} onChange={e => setAssetAccount(e.target.value)} /><Input aria-label="Счёт амортизации ОС" value={accumulatedAccount} disabled={disabled || busy || !!registerPreview} onChange={e => setAccumulatedAccount(e.target.value)} /><Input aria-label="Счёт затрат амортизации ОС" value={expenseAccount} disabled={disabled || busy || !!registerPreview} onChange={e => setExpenseAccount(e.target.value)} />
        <Input aria-label="Подразделение ОС" value={department} disabled={disabled || busy || !!registerPreview} onChange={e => setDepartment(e.target.value)} placeholder="Аналитика подразделения" /><Input aria-label="Основание регистрации ОС" value={evidence} disabled={disabled || busy || !!registerPreview} onChange={e => setEvidence(e.target.value)} placeholder="Акт и инвентарная карточка" /></div>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={disabled || busy || !!registerPreview} onClick={() => void previewRegister()}>Проверить регистрацию ОС</Button>{registerPreview && <Button disabled={disabled || busy} onClick={() => void confirmRegister()}>Сохранить ОС</Button>}</div>
      {registerPreview && <p className="text-sm text-muted">Пакет {registerPreview.digest.slice(0, 12)}… проверен. Метод: straight-line.</p>}
    </section>
    {visibleRows.map(asset => <FixedAssetRow key={asset.id} asset={asset} org={org} month={month} policyId={policyId} disabled={disabled || busy} onEntry={onEntry} />)}
    {rowsOrg === org && !visibleRows.length && <p className="text-muted">Зарегистрированных ОС нет.</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p role="status">{notice}</p>}
  </section>;
}

function FixedAssetRow({ asset, org, month, policyId, disabled, onEntry }: { asset: Asset; org: string; month: string; policyId: string; disabled: boolean; onEntry: (id: number) => void }) {
  const [postingDate, setPostingDate] = useState(`${month}-01`), [evidence, setEvidence] = useState(""), [requestId, setRequestId] = useState(requestKey), [preview, setPreview] = useState<DepPreview | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  async function inspect() {
    if (!policyId || !/^\d{4}-(0[1-9]|1[0-2])-\d{2}$/.test(postingDate) || evidence.trim().length < 10) { setError("Укажите применимую политику, дату и основание расчёта амортизации."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const command = { request_key: requestId, asset_id: asset.id, month, expected_asset_digest: asset.digest, policy_id: Number(policyId), posting_date: postingDate, dimensions: {}, evidence: evidence.trim() };
      const response = await fetch(`/api/accounting/organizations/${org}/fixed-assets/depreciation-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(command) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Амортизация не подготовлена.");
      if (String(data.organization_id) !== org || data.asset_id !== asset.id || data.month !== month || data.statutory_certified !== false || data.final_cost_certified !== false) throw new Error("Ответ расчёта амортизации не соответствует выбранной ОС.");
      setPreview({ ...data, digest: data.digest || "", posting_available: data.posting_available === true } as DepPreview); setNotice(data.posting_available ? "Расчёт проверен. Проводка ещё не создана." : "Для месяца нет суммы к проведению.");
    } catch (e) { setError(e instanceof Error ? e.message : "Амортизация не подготовлена."); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview?.posting_available || busy) return;
    setBusy(true); setError("");
    try {
      const accessResponse = await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
      const access = await accessResponse.json();
      if (!accessResponse.ok || String(access?.organization_id) !== org || typeof access.principal !== "string" || access.can_confirm !== true) throw new Error("Нет права проводить амортизацию.");
      const command = { request_key: requestId, asset_id: asset.id, month, expected_asset_digest: asset.digest, policy_id: Number(policyId), posting_date: postingDate, dimensions: {}, evidence: evidence.trim(), digest: preview.digest };
      const response = await fetch(`/api/accounting/organizations/${org}/fixed-assets/depreciation-confirm`, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": access.principal }, cache: "no-store", body: JSON.stringify(command) });
      const data = await response.json();
      if (!response.ok) {
        const recovery = await fetch(`/api/accounting/organizations/${org}/fixed-assets/depreciation-status/${encodeURIComponent(requestId)}`, { cache: "no-store" });
        if (recovery.ok) { setNotice("Амортизация уже проведена. Результат восстановлен."); setPreview(null); return; }
        throw new Error(typeof data.detail === "string" ? data.detail : "Амортизация не проведена.");
      }
      if (String(data.organization_id) !== org || data.asset_id !== asset.id || data.digest !== preview.digest) throw new Error("Ответ проведения амортизации не соответствует пакету.");
      setNotice(`Амортизация за ${month} проведена, операция № ${data.entry_id}.`); setPreview(null); setRequestId(requestKey());
      onEntry(data.entry_id);
    } catch (e) { setError(e instanceof Error ? e.message : "Амортизация не проведена."); }
    finally { setBusy(false); }
  }
  return <article className="space-y-2 rounded border border-line p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><button className="text-accent underline" onClick={() => onEntry(asset.source_entry_id)}>Источник приобретения № {asset.source_entry_id}</button><p className="font-semibold">{asset.inventory_number} · {asset.name}</p><p className="text-sm text-muted">{asset.cost} BYN · остаток {asset.residual_value} BYN · срок {asset.useful_life_months} мес. · метод {asset.depreciation_method}</p></div><span className="text-sm">Счета {asset.asset_account} / {asset.accumulated_account} / {asset.expense_account}</span></div>
    <div className="flex flex-wrap gap-2"><Input aria-label={`Дата проведения амортизации ${asset.inventory_number}`} type="date" value={postingDate} disabled={disabled || busy || !!preview} onChange={e => setPostingDate(e.target.value)} /><Input aria-label={`Основание амортизации ${asset.inventory_number}`} value={evidence} disabled={disabled || busy || !!preview} onChange={e => setEvidence(e.target.value)} placeholder="Расчёт и контроль" /><Button variant="secondary" disabled={disabled || busy || !!preview} onClick={() => void inspect()}>Проверить амортизацию</Button>{preview?.posting_available && <Button disabled={disabled || busy} onClick={() => void confirm()}>Провести амортизацию</Button>}</div>
    {preview?.calculation && <p className="text-sm text-muted">К начислению: {preview.calculation.amount} BYN · остаток после месяца: {preview.calculation.remaining_value} BYN · проводка предварительная.</p>}{error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p role="status">{notice}</p>}
  </article>;
}
