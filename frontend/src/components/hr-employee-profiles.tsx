"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { EmployeeProfileForm } from "@/components/employee-profile-form";
import { PROFILE_STATUSES } from "@/lib/employee-profile";

type Employee = { id: number; full_name: string; department: string; position: string; status: string; profile_status: string };
const EMPLOYMENT_STATUSES: Record<string, string> = { active: "Работает", needs_review: "Требует проверки", inactive: "Неактивен" };

export function HrEmployeeProfiles({ canReadPrivate, canCreate = false }: { canReadPrivate: boolean; canCreate?: boolean }) {
  const [employees, setEmployees] = useState<Employee[] | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | undefined>();
  const [reload, setReload] = useState(0);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [notice, setNotice] = useState("");
  const [name, setName] = useState("");
  const [position, setPosition] = useState("");
  const [department, setDepartment] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/hr/employees", { cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("Не удалось загрузить сотрудников. Проверьте доступ к HR.");
      const data = await response.json() as Employee[];
      if (!controller.signal.aborted) { setEmployees(data); setUncertain(false); setError(""); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Список недоступен.");
    });
    return () => controller.abort();
  }, [reload]);
  async function createEmployee(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || uncertain || !employees) return;
    const fullName = name.trim().replace(/\s+/g, " ");
    if (!fullName || !position.trim() || !department.trim()) { setNotice("Заполните ФИО, должность и отдел."); return; }
    if (employees.some((employee) => employee.full_name.trim().replace(/\s+/g, " ").toLocaleLowerCase("ru") === fullName.toLocaleLowerCase("ru"))) {
      setNotice("Сотрудник с таким ФИО уже есть в справочнике. Проверьте существующую карточку."); return;
    }
    setSaving(true); setNotice("");
    try {
      const response = await fetch("/api/hr/employees", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ full_name: fullName, position: position.trim(), department: department.trim(), status: "active" }) });
      if (response.status >= 400 && response.status < 500) { setNotice("Карточка не сохранена. Проверьте поля и право работы с кадрами."); return; }
      if (!response.ok) throw new Error("uncertain");
      const employee = await response.json() as Employee;
      if (!Number.isInteger(employee.id) || employee.full_name !== fullName) throw new Error("uncertain");
      setEmployees((current) => [employee, ...(current ?? [])]);
      setAdding(false); setName(""); setPosition(""); setDepartment("");
      setNotice("Карточка сотрудника создана. Для входа в ERP руководитель отдельно оформляет приглашение и активирует доступ.");
    } catch {
      setUncertain(true); setNotice("Результат сохранения неизвестен. Нажмите «Обновить список» и проверьте сотрудника перед повтором.");
    } finally { setSaving(false); }
  }
  return <div className="space-y-6">
    <section className="rounded-2xl bg-white p-5 shadow-card sm:p-8">
      <h1 className="text-2xl font-bold">Карточки сотрудников</h1>
      <p className="mt-2 text-sm text-muted">Сотрудники заполняют личные сведения самостоятельно. Здесь виден статус анкеты; её заполнение не меняет рабочие права.</p>
      <div className="mt-4 flex flex-wrap gap-3">
        {canCreate && <button className="rounded-xl bg-accent px-4 py-2 text-white" onClick={() => { setAdding(!adding); setNotice(""); }} disabled={saving}>Добавить сотрудника</button>}
        <button className="rounded-xl border border-line px-4 py-2" disabled={saving} onClick={() => { setError(""); setReload((value) => value + 1); }}>Обновить список</button>
      </div>
      {notice && <p role="status" className="mt-4">{notice}</p>}
      {adding && <form onSubmit={createEmployee} className="mt-5 grid gap-4 rounded-xl border border-line p-4">
        <h2 className="text-lg font-semibold">Новый сотрудник</h2>
        <p className="text-sm text-muted">Добавляйте после подтверждения приёма на работу. Для кандидатов используйте воронку подбора ниже.</p>
        <label>ФИО<input className="mt-1 w-full rounded-xl border border-line p-3" required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} disabled={saving} /></label>
        <label>Должность<input className="mt-1 w-full rounded-xl border border-line p-3" required maxLength={128} value={position} onChange={(event) => setPosition(event.target.value)} disabled={saving} /></label>
        <label>Отдел<input className="mt-1 w-full rounded-xl border border-line p-3" required maxLength={128} value={department} onChange={(event) => setDepartment(event.target.value)} disabled={saving} /></label>
        <p className="text-sm text-muted">Карточка будет иметь статус «Работает». Создание карточки не выдаёт учётную запись и не оформляет кадровые документы.</p>
        <button className="justify-self-start rounded-xl bg-accent px-4 py-2 text-white disabled:opacity-50" type="submit" disabled={saving || uncertain || !employees}>{saving ? "Сохраняем…" : "Создать карточку"}</button>
      </form>}
      {error && <p role="alert" className="mt-4 text-red-700">{error}</p>}
      {!employees && !error && <p role="status" className="mt-4">Загружаем сотрудников…</p>}
      {employees?.length === 0 && <p className="mt-4">Сотрудников пока нет.</p>}
      <ul className="mt-5 divide-y divide-line">{employees?.map((employee) => <li key={employee.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
        <div><p className="font-semibold">{employee.full_name}</p><p className="text-sm text-muted">{employee.department} · {employee.position}</p><p className="mt-1 text-sm">{EMPLOYMENT_STATUSES[employee.status] ?? "Статус требует проверки"}</p></div>
        <div className="flex items-center gap-3"><span className="text-sm">Анкета: {PROFILE_STATUSES[employee.profile_status] ?? "Не заполнена"}</span>
          {canReadPrivate && <button className="rounded-xl border border-line px-3 py-2 text-sm" onClick={() => setSelected(employee.id)}>Открыть анкету</button>}
        </div>
      </li>)}</ul>
    </section>
    <section className="rounded-2xl bg-white p-5 shadow-card sm:p-8" aria-labelledby="hire-guide">
      <h2 id="hire-guide" className="text-xl font-bold">Как добавить и принять сотрудника</h2>
      <ol className="mt-4 list-decimal space-y-3 pl-5 text-sm">
        <li>Проверьте существующую карточку по ФИО, чтобы не создавать дубль.</li>
        <li>Для нового кандидата откройте <Link className="text-accent underline" href="/erp/hr">подбор персонала</Link>. Проведите его через интервью и оффер; после подтверждения приёма переведите на этап «Нанят».</li>
        <li>Нажмите «Добавить сотрудника», укажите ФИО, должность и отдел. Этап «Нанят» в подборе сам по себе карточку сотрудника не создаёт. Кадровые документы оформляются отдельно.</li>
        <li>Если нужен вход в ERP, руководитель открывает <Link className="text-accent underline" href="/erp/settings/invitations?scope=erp">приглашения сотрудников</Link>, выбирает существующую карточку, проверяет отдел и роль, отправляет приглашение и отдельно активирует доступ.</li>
        <li>Сотрудник заполняет собственную анкету после входа. Личные сведения анкеты доступны кадровику.</li>
      </ol>
    </section>
    {selected !== undefined && <EmployeeProfileForm key={selected} employeeId={selected} />}
  </div>;
}
