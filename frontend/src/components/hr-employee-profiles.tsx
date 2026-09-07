"use client";

import { useEffect, useState } from "react";
import { EmployeeProfileForm } from "@/components/employee-profile-form";
import { PROFILE_STATUSES } from "@/lib/employee-profile";

type Employee = { id: number; full_name: string; department: string; position: string; profile_status: string };

export function HrEmployeeProfiles({ canReadPrivate }: { canReadPrivate: boolean }) {
  const [employees, setEmployees] = useState<Employee[] | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | undefined>();
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/hr/employees", { cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("Не удалось загрузить сотрудников. Проверьте доступ к HR.");
      const data = await response.json() as Employee[];
      if (!controller.signal.aborted) setEmployees(data);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Список недоступен.");
    });
    return () => controller.abort();
  }, []);
  return <div className="space-y-6">
    <section className="rounded-2xl bg-white p-5 shadow-card sm:p-8">
      <h1 className="text-2xl font-bold">Карточки сотрудников</h1>
      <p className="mt-2 text-sm text-muted">Сотрудники заполняют личные сведения самостоятельно. Здесь виден статус анкеты; её заполнение не меняет рабочие права.</p>
      {error && <p role="alert" className="mt-4 text-red-700">{error}</p>}
      {!employees && !error && <p role="status" className="mt-4">Загружаем сотрудников…</p>}
      {employees?.length === 0 && <p className="mt-4">Сотрудников пока нет.</p>}
      <ul className="mt-5 divide-y divide-line">{employees?.map((employee) => <li key={employee.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
        <div><p className="font-semibold">{employee.full_name}</p><p className="text-sm text-muted">{employee.department} · {employee.position}</p></div>
        <div className="flex items-center gap-3"><span className="text-sm">{PROFILE_STATUSES[employee.profile_status] ?? "Не заполнена"}</span>
          {canReadPrivate && <button className="rounded-xl border border-line px-3 py-2 text-sm" onClick={() => setSelected(employee.id)}>Открыть анкету</button>}
        </div>
      </li>)}</ul>
    </section>
    {selected !== undefined && <EmployeeProfileForm key={selected} employeeId={selected} />}
  </div>;
}
