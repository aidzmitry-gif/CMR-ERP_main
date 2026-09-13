"use client";

import { useEffect, useRef, useState } from "react";
import * as api from "@/lib/expense-control-api";

const field = "rounded border border-line bg-surface px-2 py-1 text-ink";
const button = `${field} disabled:opacity-50 disabled:cursor-not-allowed`;
const errorText = (e: unknown) => e instanceof Error ? e.message : "Не удалось проверить данные.";
const monthNames = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];
const parseCents = (value: string): bigint | null => {
  const negative = value.startsWith("-");
  const normalized = negative ? value.slice(1) : value;
  const [whole, fraction] = normalized.split(".");
  if (!whole || !fraction || !/^\d+$/.test(whole) || !/^\d{2}$/.test(fraction)) return null;
  const amount = BigInt(whole) * 100n + BigInt(fraction);
  return negative ? -amount : amount;
};
const formatCents = (value: bigint): string => {
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  return `${negative ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
};

export function ExpenseControl({ org }: { org?: string }) {
  const [selected, setSelected] = useState("");
  const [books, setBooks] = useState<{ id: number; name: string; unp: string }[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (org !== undefined) return;
    let active = true;
    void api.organizations().then(v => { if (active) setBooks(v); }).catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [org]);
  const chosen = org ?? selected;
  const valid = /^[1-9]\d*$/.test(chosen) && Number.isSafeInteger(Number(chosen));
  return <section aria-label="Контроль расходов" className="space-y-4">
    <h2 className="text-xl font-semibold">Контроль расходов</h2>
    <p className="text-sm text-muted">Справочник, версии бюджета и утверждение главным бухгалтером. Начисления показываются только при явной аналитике статьи; оплаты и обязательства пока не подключены.</p>
    {error && <p role="alert">{error}</p>}
    {org === undefined && <label>Юрлицо расходов <select aria-label="Юрлицо расходов" className={field} value={selected} onChange={e => setSelected(e.target.value)}>
      <option value="">Выберите юрлицо</option>{books.map(b => <option key={b.id} value={b.id}>{b.name} · {b.unp}</option>)}</select></label>}
    {valid ? <Book key={chosen} org={Number(chosen)} /> : <p>Выберите юридическое лицо. Данные других книг не объединяются.</p>}
  </section>;
}

function Book({ org }: { org: number }) {
  const [ctx, setCtx] = useState<api.Context | null>(null);
  const [view, setView] = useState<api.BudgetView | null>(null);
  const [actuals, setActuals] = useState<api.ExpenseActuals | null>(null);
  const [saved, setSaved] = useState<api.Journal>({ raw: null, attempt: null });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(true);
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [currency, setCurrency] = useState("");
  const [basis, setBasis] = useState<"" | "cash" | "accrual">("");
  const [actualMonth, setActualMonth] = useState(String(new Date().getMonth() + 1));
  const [evidence, setEvidence] = useState("");
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [group, setGroup] = useState("");
  const [cells, setCells] = useState<Record<number, string[]>>({});
  const [history, setHistory] = useState("");
  const epoch = useRef(0);
  const lock = useRef(false);
  const contextRef = useRef<api.Context | null>(null);
  const configured = currency === "BYN" && !!basis && /^20\d\d$|^2100$/.test(year);
  const pending = !!saved.attempt && ["pending", "uncertain"].includes(saved.attempt.outcome);

  function invalidateAccess(e: unknown) {
    if (!(e instanceof api.ExpenseError) || ![401, 403, 503].includes(e.status ?? 0)) return false;
    contextRef.current = null; setCtx(null); setView(null); setActuals(null); setCells({}); setHistory("");
    setSaved({ raw: null, attempt: null }); setNotice(""); setEvidence(""); setCode(""); setTitle(""); setGroup("");
    return true; // Durable journal stays in storage for its original principal.
  }
  async function load(token: number) {
    const current = await api.context(org);
    if (token !== epoch.current) return;
    contextRef.current = current;
    setCtx(current); setView(null); setActuals(null); setCells({}); setHistory(""); setSaved({ raw: null, attempt: null });
    const scope = { org, principal: current.principal };
    const next = await api.journal(scope);
    const data = configured && basis ? await api.getBudgets(scope, Number(year), basis) : null;
    const actual = configured && basis ? await api.getActuals(scope, Number(year), Number(actualMonth), basis) : null;
    if (token !== epoch.current) return;
    setSaved(next); setView(data); setActuals(actual);
    if (data) {
      const latest = data.versions[0];
      const inputs: Record<number, string[]> = {};
      for (const a of current.catalog.articles.filter(a => a.active)) inputs[a.id] = Array(12).fill("");
      for (const row of latest?.lines ?? []) inputs[row.article_id] = row.months.map(v => v ?? "");
      setCells(inputs);
    }
  }
  useEffect(() => {
    const token = ++epoch.current;
    lock.current = true;
    void load(token).catch(e => { if (token === epoch.current) { invalidateAccess(e); setError(errorText(e)); } }).finally(() => {
      if (token === epoch.current) { lock.current = false; setBusy(false); }
    });
    return () => { epoch.current = token + 1; };
    // The parent remounts the entire book on any organization change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org]);

  async function run(action: (token: number) => Promise<void>) {
    if (lock.current) return;
    const token = epoch.current; lock.current = true; setBusy(true); setError(""); setNotice("");
    try { await action(token); }
    catch (e) {
      if (token === epoch.current) {
        setError(errorText(e));
        if (invalidateAccess(e)) return;
        const current = contextRef.current;
        if (current) try {
          const next = await api.journal({ org, principal: current.principal });
          if (token === epoch.current) setSaved(next);
        } catch (e) { if (token === epoch.current) setError(errorText(e)); }
      }
    } finally { if (token === epoch.current) { lock.current = false; setBusy(false); } }
  }
  async function send(token: number, kind: api.Attempt["kind"], body: api.CatalogBody | api.BudgetBody | api.ApprovalBody) {
    if (!ctx) return;
    const scope = { org, principal: ctx.principal };
    await api.context(org, ctx.principal);
    if (token !== epoch.current) return;
    const next = await api.begin(scope, kind, body, saved.raw);
    if (token !== epoch.current) return;
    setSaved(next);
    const result = await api.dispatch(next, "first");
    if (token !== epoch.current) return;
    setSaved(result.journal);
    await load(token);
    if (token === epoch.current) setNotice(`Команда подтверждена. Квитанция ${result.receipt.request_key}.`);
  }
  function catalog(action: api.CatalogBody["action"], target_id: number | null = null) {
    void run(async token => {
      if (!ctx || !evidence.trim()) return;
      const create = action.startsWith("create");
      await send(token, "catalog", { request_key: crypto.randomUUID(), expected_revision: ctx.catalog.revision,
        evidence: evidence.trim(), action, code: create ? code.trim() : null, title: create ? title.trim() : null,
        group_id: action === "create_article" ? Number(group) : null, target_id });
    });
  }
  function budget() {
    void run(async token => {
      if (!ctx || !view || !basis || !configured) return;
      const lines = Object.entries(cells).map(([id, values]) => ({ article_id: Number(id), months: values.map(v => {
        const input = v.trim(); if (!input) return null;
        if (!/^(0|[1-9][0-9]{0,15})([.,][0-9]{1,2})?$/.test(input)) throw new Error("Сумма: неотрицательное число, максимум две цифры после запятой.");
        const [whole, fraction = ""] = input.replace(",", ".").split("."); return `${whole}.${fraction.padEnd(2, "0")}`;
      }) })).sort((a, b) => a.article_id - b.article_id);
      await send(token, "budget", { request_key: crypto.randomUUID(), expected_revision: view.versions[0]?.revision ?? 0,
        expected_catalog_revision: ctx.catalog.revision, year: Number(year), currency: "BYN", basis, evidence: evidence.trim(), lines });
    });
  }
  function approve() {
    void run(async token => {
      const latest = view?.versions[0];
      if (!ctx || !view || !latest || !view.approval_enabled || ctx.role !== "chief" || !evidence.trim()) return;
      await send(token, "approval", {
        request_key: crypto.randomUUID(), budget_id: latest.id,
        expected_revision: latest.revision, evidence: evidence.trim(),
      });
    });
  }
  function recover(mode: "recover" | "retry") {
    void run(async token => {
      const result = await api.dispatch(saved, mode);
      if (token !== epoch.current) return;
      setSaved(result.journal); await load(token);
      if (token === epoch.current) setNotice(`Исходная команда подтверждена: ${result.receipt.request_key}.`);
    });
  }
  function configure(action: () => void) { action(); setView(null); setActuals(null); setCells({}); setHistory(""); }
  const editable = !busy && !pending && !!ctx && ctx.role !== "reader";
  const chief = editable && ctx?.role === "chief";
  const historyBudget = view?.versions.find(v => String(v.revision) === history);
  return <div className="space-y-4">
    {busy && <p role="status">Проверка и сохранение…</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {ctx && <p>Книга № {org}. Учётная запись: {ctx.principal}. Версия справочника: {ctx.catalog.revision}.</p>}
    <button className={button} disabled={busy} onClick={() => void run(load)}>Обновить сведения</button>
    {pending && <div className="rounded border border-amber-400 p-3">
      <p>Результат исходной команды не установлен. UUID: {JSON.parse(saved.attempt!.body).request_key}. Новая команда заблокирована.</p>
      <button className={button} disabled={busy} onClick={() => recover("recover")}>Проверить исходную команду</button>{" "}
      <button className={button} disabled={busy} onClick={() => recover("retry")}>Повторить исходную команду</button>
    </div>}
    {saved.attempt?.outcome === "rejected" && <p>Сервер отклонил команду. Обновите сведения перед исправлением.</p>}
    <div className="flex flex-wrap gap-3">
      <label>Год <input aria-label="Год бюджета" className={field} value={year} disabled={busy} onChange={e => configure(() => setYear(e.target.value))} /></label>
      <label>Валюта <select aria-label="Валюта бюджета" className={field} value={currency} disabled={busy} onChange={e => configure(() => setCurrency(e.target.value))}><option value="">Выберите валюту</option><option value="BYN">BYN</option></select></label>
      <label>Основа <select aria-label="Основа бюджета" className={field} value={basis} disabled={busy} onChange={e => configure(() => setBasis(e.target.value as typeof basis))}><option value="">Выберите основу</option><option value="cash">Денежные выплаты</option><option value="accrual">Начисления</option></select></label>
      <label>Месяц факта <select aria-label="Месяц факта" className={field} value={actualMonth} disabled={busy} onChange={e => configure(() => setActualMonth(e.target.value))}>{monthNames.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}</select></label>
      <button className={button} disabled={busy || !configured} onClick={() => void run(load)}>Загрузить бюджет</button>
    </div>
    <p className="text-sm text-muted">В этом срезе поддерживается BYN, без пересчёта валют. Пустой месяц — неизвестно; явный 0 — нулевой черновой план. Таблица Google не импортируется.</p>
    {ctx && <>
      <label className="block">Основание изменения <input aria-label="Основание изменения" className={`${field} w-full`} value={evidence} disabled={!editable} onChange={e => setEvidence(e.target.value)} /></label>
      <details><summary>Справочник групп и статей</summary>
        <p className="my-2 text-sm">Контрагент, договор, офис/склад и подразделение не являются статьями расходов. Управление справочником доступно главному бухгалтеру.</p>
        {!ctx.catalog.groups.length && <div className="rounded border border-line p-3"><p>Шаблон: 6 групп и 15 статей. Создаст только справочник в книге № {org}, без сумм и операций.</p>
          <ul>{ctx.template.map(g => <li key={g.code}>{g.title}: {g.articles.map(a => a.title).join("; ")}</li>)}</ul>
          <button className={button} disabled={!chief || !evidence.trim()} onClick={() => catalog("template")}>Создать справочник из шаблона в этой организации</button></div>}
        {ctx.catalog.groups.map(g => <div key={g.id} className="my-2 rounded border border-line p-3">
          <strong>{g.title}</strong> · {g.code} {!g.active && "(архив)"}{" "}
          {g.active && <button className={button} disabled={!chief || !evidence.trim()} onClick={() => catalog("archive_group", g.id)}>Архивировать группу {g.title}</button>}
          <ul>{ctx.catalog.articles.filter(a => a.group_id === g.id).map(a => <li key={a.id}>{a.title} · {a.code} {!a.active && "(архив)"}{" "}
            {a.active && <button className={button} disabled={!chief || !evidence.trim()} onClick={() => catalog("archive_article", a.id)}>Архивировать статью {a.title}</button>}</li>)}</ul>
        </div>)}
        <div className="flex flex-wrap gap-2"><label>Код <input aria-label="Код справочника" className={field} value={code} disabled={!chief} onChange={e => setCode(e.target.value)} /></label>
          <label>Название <input aria-label="Название справочника" className={field} value={title} disabled={!chief} onChange={e => setTitle(e.target.value)} /></label>
          <button className={button} disabled={!chief || !code.trim() || !title.trim() || !evidence.trim()} onClick={() => catalog("create_group")}>Создать группу</button>
          <select aria-label="Группа новой статьи" className={field} value={group} disabled={!chief} onChange={e => setGroup(e.target.value)}><option value="">Выберите группу</option>{ctx.catalog.groups.filter(g => g.active).map(g => <option key={g.id} value={g.id}>{g.title}</option>)}</select>
          <button className={button} disabled={!chief || !code.trim() || !title.trim() || !group || !evidence.trim()} onClick={() => catalog("create_article")}>Создать статью</button></div>
      </details>
      <p>{ctx.approval_blocker ?? "Утверждение доступно главному бухгалтеру после проверки последней версии."}</p>
      <button className={button} disabled={!chief || !view?.versions[0] || !evidence.trim()
        || view.approved_plan?.budget_revision === view.versions[0]?.revision} onClick={approve}>Утвердить бюджет</button>
    </>}
    <div className="grid gap-3 md:grid-cols-4">{["Утверждённый план", "Начислено", "Оплачено", "Непогашенные обязательства"].map(label => {
      const value = label === "Утверждённый план" && view?.approved_plan ? `Версия ${view.approved_plan.budget_revision}`
        : label === "Начислено" && actuals?.amount ? `${actuals.amount} BYN` : "— Неизвестно";
      return <div key={label} className="rounded border border-line p-3"><strong>{label}</strong><p>{value}</p><p className="text-xs text-muted">{label === "Утверждённый план" ? (view?.approved_plan ? `Утвердил: ${view.approved_plan.approved_by}` : "Утверждение ещё не выполнено") : label === "Начислено" && actuals ? actuals.reason : "Адаптер подтверждённых данных не подключён"}</p></div>;
    })}</div>
    {actuals && <div aria-label="Фактические начисления расходов" className="rounded border border-line p-3"><h3 className="font-semibold">Начисленные расходы за {actuals.month} месяц</h3><p className="text-sm text-muted">Покрытие: {actuals.coverage}. Учтено строк: {actuals.matched_lines}; без статьи: {actuals.unmatched_lines ?? "не определено"}.</p>{actuals.rows.length ? <ul>{actuals.rows.map(row => <li key={row.article_id}>{row.group_title ?? "Без группы"} / {row.article_title}: {row.amount} BYN ({row.lines} строк)</li>)}</ul> : <p>{actuals.reason}</p>}</div>}
    {actuals && actuals.rows.length > 0 && <div aria-label="План-факт расходов" className="rounded border border-line p-3"><h3 className="font-semibold">План-факт за {actuals.month} месяц</h3><p className="text-sm text-muted">Отклонение = факт минус план. При неполном покрытии показана только размеченная часть факта; строки без плана остаются неизвестными.</p><div className="overflow-x-auto"><table className="text-sm"><thead><tr><th className="p-2 text-left">Группа / статья</th><th className="p-2 text-right">План</th><th className="p-2 text-right">Факт</th><th className="p-2 text-right">Отклонение</th></tr></thead><tbody>{actuals.rows.map(row => {
      const plan = view?.versions[0]?.lines.find(line => line.article_id === row.article_id)?.months[actuals.month - 1] ?? null;
      const delta = plan === null ? null : (() => { const planned = parseCents(plan); const actual = parseCents(row.amount); return planned === null || actual === null ? null : formatCents(actual - planned); })();
      return <tr key={row.article_id}><th className="p-2 text-left">{row.group_title ?? "Без группы"} / {row.article_title}</th><td className="p-2 text-right">{plan === null ? "неизвестно" : `${plan} BYN`}</td><td className="p-2 text-right">{row.amount} BYN</td><td className="p-2 text-right">{delta === null ? "неизвестно" : `${delta} BYN`}</td></tr>;
    })}</tbody></table></div></div>}
    {view && ctx && <>
      <h3 className="font-semibold">Черновик {view.year} · BYN · {view.basis === "cash" ? "денежные выплаты" : "начисления"}</h3>
      <p>Последняя версия: {view.versions[0]?.revision ?? "ещё нет"}. Сохранение создаст новую версию; прежние останутся в истории.</p>
      {!Object.keys(cells).length ? <p>Создайте статьи расходов, чтобы подготовить черновик.</p> : <div className="overflow-x-auto"><table className="text-sm"><thead><tr><th>Группа / статья</th>{monthNames.map(m => <th key={m}>{m}</th>)}</tr></thead>
        <tbody>{Object.entries(cells).map(([id, values]) => { const a = ctx.catalog.articles.find(a => a.id === Number(id)); const g = ctx.catalog.groups.find(g => g.id === a?.group_id);
          return <tr key={id}><th className="p-2 text-left">{g?.title} / {a?.title ?? id}{!a?.active && " (архив)"}</th>{values.map((v, i) => <td key={i}><input className={`${field} w-24`} aria-label={`${a?.title ?? id} ${monthNames[i]}`} inputMode="decimal" value={v} placeholder="—" disabled={!editable || !a?.active}
            onChange={e => setCells(prev => ({ ...prev, [id]: prev[Number(id)].map((old, n) => n === i ? e.target.value : old) }))} /></td>)}</tr>;
        })}</tbody></table></div>}
      <button className={button} disabled={!editable || !evidence.trim() || !Object.keys(cells).length} onClick={budget}>Сохранить новую версию черновика</button>
      <label className="block">История версий <select aria-label="История версий" className={field} value={history} onChange={e => setHistory(e.target.value)}><option value="">Выберите версию для просмотра</option>{view.versions.map(v => <option key={v.id} value={v.revision}>Версия {v.revision} · {v.actor}</option>)}</select></label>
      {historyBudget && <div aria-label="Исторический черновик"><p>Версия {historyBudget.revision}. Основание: {historyBudget.evidence}</p><ul>{historyBudget.lines.map(l => <li key={l.article_id}>{l.article_snapshot.group.title} / {l.article_snapshot.title}: {l.months.map((v, i) => `${monthNames[i]} ${v ?? "неизвестно"}`).join("; ")}</li>)}</ul></div>}
    </>}
  </div>;
}
