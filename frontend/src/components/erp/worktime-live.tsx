"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { clockLabel, minutesLabel, readPending, validWorkSession, worktimeRequest, WorktimeError,
  type WorkBoard, type WorkContext, type WorkDay, type WorkPending, type WorkSettings, type WorkSheet } from "@/lib/worktime";

const button = "rounded-lg border border-line px-4 py-2 text-sm font-medium disabled:opacity-50";
const field = "min-w-0 max-w-full rounded-lg border border-line bg-surface px-3 py-2 text-ink";
const panel = "min-w-0 rounded-2xl border border-line bg-surface p-5";
const errorText = (e: unknown) => e instanceof Error ? e.message : "Не удалось получить данные";
const storageKey = (id: number) => "hr.worktime.pending." + id;
const dateTime = (v: string) => new Date(v).toLocaleString("ru-RU", { timeZone: "Europe/Minsk" });

function Presence() {
  const [data, setData] = useState<WorkBoard | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const [department, setDepartment] = useState("");
  const seq = useRef(0);
  const invalidate = useCallback(() => { seq.current++; }, []);
  const reload = useCallback(async () => {
    const current = ++seq.current;
    setLoading(true); setData(null); setError("");
    try { const next = await worktimeRequest<WorkBoard>("worktime/board"); if (!Array.isArray(next.items)) throw new Error("Неполный список присутствия"); if (current === seq.current) setData(next); }
    catch (e) { if (current === seq.current) setError(errorText(e)); } finally { if (current === seq.current) setLoading(false); }
  }, []);
  useEffect(() => { let cancelled = false; void Promise.resolve().then(() => { if (!cancelled) void reload(); }); return () => { cancelled = true; invalidate(); }; }, [reload, invalidate]);
  const rows = data?.items.filter(row => !department || row.employee.department === department) ?? [];
  return <section className={panel}><h2 className="text-lg font-semibold">Присутствие сотрудников</h2>
    <button className={button + " my-3"} disabled={loading} onClick={() => void reload()}>Обновить присутствие</button><ErrorNotice text={error} />
    {loading ? <p role="status">Загрузка присутствия…</p> : data && <>
      <p className="my-3 text-sm">Состояние на {dateTime(data.server_now)}. Присутствие не меняет часы табеля.</p>
      <label>Отдел <select className={field} value={department} onChange={e => setDepartment(e.target.value)}><option value="">Все доступные</option>{Array.from(new Set(data.items.map(row => row.employee.department))).filter(Boolean).map(name => <option key={name}>{name}</option>)}</select></label>
      {rows.length === 0 ? <p className="mt-3">Нет доступных сотрудников</p> : <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Сотрудник</th><th>Присутствие в ERP</th><th>Рабочий день</th><th>Между кнопками</th></tr></thead><tbody>{rows.map(({ employee, session, present }) => <tr className="border-t border-line" key={employee.id}><td className="py-3">{employee.full_name}<span className="block text-muted">{employee.department}</span></td><td>{present ? "Подтверждено" : "Не подтверждено"}</td><td>{!session ? "Не начат" : session.ended_at ? "Завершён" : "Начат"}</td><td>{session ? clockLabel(session.elapsed_seconds) : "—"}</td></tr>)}</tbody></table></div>}
    </>}
  </section>;
}

function MonthGrid({ data, onSelect }: { data: WorkSheet; onSelect: (day: WorkDay) => void }) {
  const [year, month] = data.period.split("-").map(Number);
  const days = Array.from({ length: new Date(year, month, 0).getDate() }, (_, i) => i + 1);
  return <div className="my-4 overflow-x-auto"><table aria-label="Месячная сетка табеля" className="w-full border-collapse text-center text-sm">
    <thead><tr><th className="sticky left-0 min-w-40 bg-surface p-2 text-left">Сотрудник</th>{days.map(day => <th key={day} className="min-w-12 p-2">{day}</th>)}<th className="min-w-20">Дней</th><th className="min-w-20">Часы</th>{["О", "Б", "К", "А"].map(code => <th key={code} className="min-w-10">{code}</th>)}</tr></thead>
    <tbody>{data.employees.map(employee => {
      const records = data.items.filter(row => row.employee_id === employee.id);
      return <tr key={employee.id} className="border-t border-line"><th className="sticky left-0 bg-surface p-2 text-left font-normal">{employee.full_name}</th>{days.map(day => {
        const date = data.period + "-" + String(day).padStart(2, "0");
        const row = records.find(item => item.date === date);
        return <td key={day} className="border-l border-line p-1">{row ? <button type="button" className="min-h-8 min-w-10 rounded hover:bg-blue-50" title={date + (row.extra_minutes ? " · есть переработка" : "")} onClick={() => onSelect(row)}>{row.code ?? minutesLabel(row.credited_minutes)}{row.approval_status === "pending" && " *"}</button> : <span title="Нет подтверждённой записи">—</span>}</td>;
      })}<td>{records.filter(row => !row.code && row.credited_minutes > 0).length || "—"}</td><td>{records.length ? minutesLabel(records.reduce((sum, row) => sum + row.credited_minutes, 0)) : "—"}</td>{["О", "Б", "К", "А"].map(code => <td key={code}>{records.filter(row => row.code === code).length || "—"}</td>)}</tr>;
    })}</tbody>
  </table><p className="mt-2 text-xs text-muted">Часы:минуты. «—» — запись отсутствует; * — переработка ожидает согласования. О — отпуск, Б — больничный, К — командировка, А — административный отпуск, В — выходной.</p></div>;
}

function Timesheet({ today, initialPeriod }: { today: string; initialPeriod?: string }) {
  const [period, setPeriod] = useState(initialPeriod ?? today.slice(0, 7)), [data, setData] = useState<WorkSheet | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(""), [selected, setSelected] = useState<WorkDay | null>(null);
  const [reason, setReason] = useState(""), [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const invalidate = useCallback(() => { seq.current++; }, []);
  const reload = useCallback(async () => {
    const current = ++seq.current; setLoading(true); setData(null);
    try {
      const next = await worktimeRequest<WorkSheet>("worktime/timesheet?period=" + encodeURIComponent(period));
      if (next.period !== period || !Array.isArray(next.items) || !Array.isArray(next.employees)) throw new Error("Неполный табель");
      if (current === seq.current) setData(next);
    } catch (e) { if (current === seq.current) setError(errorText(e)); }
    finally { if (current === seq.current) setLoading(false); }
  }, [period]);
  useEffect(() => { let cancelled = false; void Promise.resolve().then(() => { if (!cancelled) void reload(); }); return () => { cancelled = true; invalidate(); }; }, [reload, invalidate]);
  async function decide(approved: boolean) {
    if (!selected || busy) return;
    setBusy(true); setError("");
    try { await worktimeRequest("worktime/days/" + selected.id + "/decision", { approved, reason }); setSelected(null); await reload(); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <section className={panel}><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">Табель рабочего времени</h2>
    <label>Месяц <input type="month" className={field} value={period} disabled={busy} onChange={e => { if (e.target.value) { setSelected(null); setError(""); setPeriod(e.target.value); } }} /></label>
    <button className={button} disabled={loading || busy} onClick={() => void reload()}>Обновить табель</button></div>
    <p className="my-3 text-sm text-muted">Учтены полные часы между кнопками в пределах нормы. Переработка добавляется после согласования. Зарплата автоматически не начисляется.</p><ErrorNotice text={error} />
    {!loading && data && <MonthGrid data={data} onSelect={row => { setSelected(row); setReason(""); }} />}
    {loading ? <p role="status">Загрузка табеля…</p> : data && (data.items.length === 0 ? <p>За этот месяц нет подтверждённых записей</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Сотрудник</th><th>Дата</th><th>Между кнопками</th><th>Норма</th><th>В табеле</th><th>Переработка</th></tr></thead><tbody>{data.items.map(row => <tr key={row.id} className="border-t border-line"><td className="py-3">{data.employees.find(employee => employee.id === row.employee_id)?.full_name ?? "Сотрудник №" + row.employee_id}</td><td>{row.date}</td><td>{row.code ?? clockLabel(row.worked_seconds)}</td><td>{minutesLabel(row.norm_minutes)}</td><td>{row.code ?? minutesLabel(row.credited_minutes)}</td><td>{row.extra_minutes ? <>{minutesLabel(row.extra_minutes)} · {row.approval_status === "approved" ? "Согласована" : row.approval_status === "rejected" ? "Отклонена" : "Ожидает согласования"}{row.can_decide && <button className={button + " ml-2"} onClick={() => { setSelected(row); setReason(""); }}>Рассмотреть</button>}</> : "—"}</td></tr>)}</tbody></table></div>)}
    {selected && <div role="dialog" aria-modal="true" aria-label="Согласование переработки" className="mt-4 rounded-xl border border-line p-4"><h3>Переработка за {selected.date}: {minutesLabel(selected.extra_minutes)}</h3>
      <p>Между кнопками: {clockLabel(selected.worked_seconds)}. Норма: {minutesLabel(selected.norm_minutes)}. В табеле: {selected.code ?? minutesLabel(selected.credited_minutes)}.</p>
      {selected.can_decide && <label className="my-3 block">Основание решения <textarea className={field + " block w-full"} value={reason} onChange={e => setReason(e.target.value)} maxLength={500} /></label>}
      <div className="flex gap-2">{selected.can_decide && <><button className={button} disabled={busy || reason.trim().length < 3} onClick={() => void decide(true)}>Согласовать</button><button className={button} disabled={busy || reason.trim().length < 3} onClick={() => void decide(false)}>Отклонить</button></>}<button className={button} disabled={busy} onClick={() => setSelected(null)}>Закрыть</button></div>
    </div>}
  </section>;
}

function Settings({ today }: { today: string }) {
  const [data, setData] = useState<WorkSettings | null>(null), [error, setError] = useState(""), [success, setSuccess] = useState("");
  const [employee, setEmployee] = useState(""), [busy, setBusy] = useState(false);
  const [absenceIntent, setAbsenceIntent] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    let active = true;
    worktimeRequest<WorkSettings>("worktime/settings").then(next => {
      if (!Array.isArray(next.employees) || !Array.isArray(next.managers)) throw new Error("Неполные настройки");
      if (active) setData(next);
    }).catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>, absence: boolean) {
    event.preventDefault(); if (busy) return;
    const values = new FormData(event.currentTarget);
    setBusy(true); setError(""); setSuccess("");
    try {
      if (absence) {
        const intent = absenceIntent ?? { employee_id: Number(values.get("employee")), work_date: values.get("date"), code: values.get("code"), reference: values.get("reference"), request_key: crypto.randomUUID() };
        setAbsenceIntent(intent); await worktimeRequest("worktime/absences", intent); setAbsenceIntent(null);
        setSuccess("Код отсутствия сохранён в табеле");
      } else {
        const [h, m] = String(values.get("start") || "").split(":").map(Number);
        const weekmask = values.getAll("weekday").reduce<number>((sum, day) => sum | 1 << Number(day), 0);
        if (!weekmask) throw new Error("Выберите рабочие дни по договору");
        await worktimeRequest("worktime/policies", { employee_id: Number(employee), effective_from: values.get("effective"), daily_minutes: Number(values.get("minutes")), weekmask, start_minute: values.get("start") ? h * 60 + m : null, manager_id: Number(values.get("manager")), reference: values.get("reference") });
        setSuccess("Норма и руководитель сохранены. Исторические записи не изменены");
      }
    } catch (e) { if (e instanceof WorktimeError && e.rejected) setAbsenceIntent(null); setError(errorText(e)); }
    finally { setBusy(false); }
  }
  return <section className={panel}><h2 className="text-lg font-semibold">Настройки договора и коды отсутствия</h2><ErrorNotice text={error} />{success && <p role="status" className="my-3 text-emerald-700">{success}</p>}
    {!data ? !error && <p>Загрузка настроек…</p> : <div className="mt-4 grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-2">
      <form onSubmit={e => void submit(e, false)} className="grid min-w-0 grid-cols-1 content-start gap-3"><h3 className="font-medium">Норма по договору</h3><fieldset disabled={busy} className="grid min-w-0 grid-cols-1 gap-3">
        <label>Сотрудник <select required className={field + " block w-full"} value={employee} onChange={e => setEmployee(e.target.value)}><option value="">Выберите сотрудника</option>{data.employees.map(row => <option key={row.id} value={row.id}>{row.full_name}</option>)}</select></label>
        <label>Действует с <input required name="effective" type="date" defaultValue={today} className={field + " block"} /></label>
        <label>Норма рабочего дня, минут <input required name="minutes" type="number" min={1} max={1440} step={1} className={field + " block"} /></label>
        <div>Рабочие дни<div className="flex flex-wrap gap-3">{["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((day, i) => <label key={day}><input type="checkbox" name="weekday" value={i} /> {day}</label>)}</div></div>
        <label>Плановое начало (необязательно) <input name="start" type="time" className={field + " block"} /></label>
        <label>Руководитель <select required name="manager" className={field + " block w-full"} defaultValue=""><option value="">Выберите руководителя</option>{data.managers.filter(row => row.employee_id !== Number(employee)).map(row => <option key={row.id} value={row.id}>{row.full_name}</option>)}</select></label>
        <label>Основание по договору <input required name="reference" minLength={5} maxLength={300} className={field + " block w-full"} /></label><button className={button}>Сохранить норму</button>
      </fieldset></form>
      <form onSubmit={e => void submit(e, true)} className="grid min-w-0 grid-cols-1 content-start gap-3"><h3 className="font-medium">Код отсутствия</h3><fieldset disabled={busy || !!absenceIntent} className="grid min-w-0 grid-cols-1 gap-3">
        <label>Сотрудник <select required name="employee" className={field + " block w-full"} defaultValue=""><option value="">Выберите сотрудника</option>{data.employees.map(row => <option key={row.id} value={row.id}>{row.full_name}</option>)}</select></label>
        <label>Дата <input required name="date" type="date" max={today} defaultValue={today} className={field + " block"} /></label>
        <label>Код <select name="code" className={field + " block"}><option value="В">В — выходной</option><option value="О">О — отпуск</option><option value="Б">Б — больничный</option><option value="К">К — командировка</option><option value="А">А — административный отпуск</option></select></label>
        <label>Основание <input required name="reference" minLength={5} maxLength={300} className={field + " block w-full"} /></label>
      </fieldset><button disabled={busy} className={button}>{absenceIntent ? "Повторить сохранение кода" : "Сохранить код"}</button><p className="text-sm text-muted">Код не заменяет уже записанное рабочее время.</p></form>
    </div>}
  </section>;
}

export function WorktimeView({ initialTab = "day", initialPeriod }: { initialTab?: "day" | "sheet"; initialPeriod?: string }) {
  const [tab, setTab] = useState<string>(initialTab), [access, setAccess] = useState<WorkSheet | null>(null);
  const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Minsk" }).format(new Date());
  useEffect(() => {
    let active = true;
    worktimeRequest<WorkSheet>("worktime/timesheet?period=" + today.slice(0, 7)).then(data => { if (active) setAccess(data); }).catch(() => {});
    return () => { active = false; };
  }, [today]);
  const tabs = [["day", "Мой день"], ["presence", "Кто онлайн"], ["sheet", "Табель"], ...(access?.can_configure ? [["settings", "Настройки"]] : [])];
  return <div className="min-w-0 flex-1 space-y-4 p-4 sm:p-6"><div><h1 className="text-2xl font-semibold">Учёт рабочего времени</h1><p className="mt-2 text-sm text-muted">Часы считаются между «Начать день» и «Завершить день». Присутствие в ERP показывается отдельно.</p></div>
    <nav className="flex flex-wrap gap-2" aria-label="Учёт времени">{tabs.map(([key, title]) => <button key={key} className={button + (tab === key ? " bg-accent text-white" : " bg-surface")} aria-current={tab === key ? "page" : undefined} onClick={() => setTab(key)}>{title}</button>)}</nav>
    {tab === "day" ? <MyDay /> : tab === "presence" ? <Presence /> : tab === "sheet" ? <Timesheet today={today} initialPeriod={initialPeriod} /> : <Settings today={today} />}
  </div>;
}

function ErrorNotice({ text }: { text: string }) {
  return text ? <p role="alert" className="my-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{text}</p> : null;
}

function MyDay() {
  const [context, setContext] = useState<WorkContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<WorkPending | null>(null);
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const alive = useRef(true), version = useRef(0), commandBusy = useRef(false), received = useRef(0);
  const invalidate = useCallback(() => { alive.current = false; version.current++; }, []);
  const reload = useCallback(async () => {
    if (commandBusy.current) return;
    const seq = ++version.current;
    setLoading(true);
    try {
      const next = await worktimeRequest<WorkContext>("me/worktime");
      if (!next.employee?.id || next.time_rule !== "between_buttons" || next.presence_affects_hours !== false
          || !/^\d{4}-\d{2}-\d{2}$/.test(next.today)
          || next.session && !validWorkSession(next.session, next.employee.id)) throw new Error("Неполные данные рабочего дня");
      if (!alive.current || seq !== version.current) return;
      received.current = performance.now();
      setContext(next); setSeconds(next.session?.elapsed_seconds ?? 0);
      setPending(readPending(sessionStorage.getItem(storageKey(next.employee.id)), next.employee.id));
    } catch (e) { if (alive.current && seq === version.current) { setContext(null); setError(errorText(e)); } }
    finally { if (alive.current && seq === version.current) setLoading(false); }
  }, []);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => { if (alive.current) void reload(); }); return invalidate; }, [reload, invalidate]);
  useEffect(() => {
    const session = context?.session;
    if (!session || session.ended_at) return;
    const timer = setInterval(() => setSeconds(session.elapsed_seconds + Math.floor((performance.now() - received.current) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [context]);

  async function command(action: "start" | "end") {
    if (!context || commandBusy.current) return;
    commandBusy.current = true; version.current++; setBusy(true); setError("");
    let intent = pending;
    try {
      if (!intent) {
        intent = { employee_id: context.employee.id, request_key: crypto.randomUUID(), action,
          ...(action === "end" ? { session_id: context.session?.id } : {}) };
        sessionStorage.setItem(storageKey(context.employee.id), JSON.stringify(intent)); setPending(intent);
      }
      const { action: operation, ...body } = intent;
      const result = await worktimeRequest("me/worktime/" + operation, body);
      if (!validWorkSession(result, context.employee.id) || operation === "end" && !result.ended_at)
        throw new Error("Ответ не подтверждает сохранение. Повторите тот же запрос");
      sessionStorage.removeItem(storageKey(context.employee.id));
      if (alive.current) { setPending(null); received.current = performance.now(); setContext({ ...context, session: result }); setSeconds(result.elapsed_seconds); }
    } catch (e) {
      if (e instanceof WorktimeError && e.rejected) {
        sessionStorage.removeItem(storageKey(context.employee.id)); if (alive.current) setPending(null);
      }
      if (alive.current) setError(errorText(e));
    } finally { commandBusy.current = false; if (alive.current) { setBusy(false); void reload(); } }
  }

  return <section className={panel} aria-busy={loading || busy}>
    <h2 className="text-lg font-semibold">Мой рабочий день</h2><ErrorNotice text={error} />
    {loading ? <p role="status">Проверяем сохранённый рабочий день…</p> : !context
      ? <button className={button} onClick={() => void reload()}>Повторить загрузку</button> : <>
      <p className="mt-2">{context.employee.full_name} · {context.today} · Минск</p>
      <p className="my-4 font-mono text-4xl" aria-label="Время между кнопками">{clockLabel(seconds)}</p>
      <p>{context.session ? context.session.ended_at ? "День завершён" : "День начат" : "День ещё не начат"}</p>
      {context.session && <p className="my-2 text-sm">Начало: {dateTime(context.session.started_at)}{context.session.ended_at && " · Завершение: " + dateTime(context.session.ended_at)}</p>}
      <p className="my-3">Норма по договору: {context.policy ? minutesLabel(context.policy.daily_minutes) : "не настроена"}</p>
      {context.policy?.start_minute != null && <p className="my-2 text-sm">Плановое начало: {minutesLabel(context.policy.start_minute)}. {context.session?.ended_at ? "" : context.session ? "Завершите день после окончания работы." : "Начните день, когда приступите к работе."}</p>}
      {!context.policy && <p className="my-3 text-amber-700">Для начала дня HR должен указать норму и руководителя по договору.</p>}
      {pending ? <button disabled={busy} className={button} onClick={() => void command(pending.action)}>Повторить {pending.action === "start" ? "начало" : "завершение"} дня</button>
        : !context.session ? <button disabled={busy || !context.policy} className={button} onClick={() => void command("start")}>Начать день</button>
        : !context.session.ended_at ? <button disabled={busy} className={button} onClick={() => void command("end")}>Завершить день</button> : null}
      <button className={button + " ml-2"} disabled={busy} onClick={() => void reload()}>Обновить</button>
      {context.session && !context.session.ended_at && <p className="mt-3 text-sm" role="status">Присутствие отмечается, пока открыта видимая вкладка ERP. Начатый день учитывается независимо от присутствия. Не забудьте завершить день.</p>}
    </>}
  </section>;
}
