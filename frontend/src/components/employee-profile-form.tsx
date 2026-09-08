"use client";

import { useEffect, useState } from "react";
import { ageOn, PROFILE_STATUSES, type EmployeeProfile } from "@/lib/employee-profile";

const inputClass = "mt-2 w-full rounded-xl border border-line bg-surface px-3 py-3 text-ink disabled:bg-sunken [color-scheme:light] dark:[color-scheme:dark]";

export function EmployeeProfileForm({ employeeId }: { employeeId?: number }) {
  return <ProfileFormContent key={employeeId ?? "self"} employeeId={employeeId} />;
}

function ProfileFormContent({ employeeId }: { employeeId?: number }) {
  const [profile, setProfile] = useState<EmployeeProfile | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const readOnly = employeeId !== undefined;

  useEffect(() => {
    const controller = new AbortController();
    fetch(readOnly ? `/api/hr/employee-profiles/${employeeId}` : "/api/hr/me/profile", {
      cache: "no-store", signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 403
        ? "Нет доступа к личным сведениям. Проверьте вход и связь учётной записи с HR-карточкой."
        : "Не удалось загрузить карточку. Обновите страницу.");
      const data = await response.json() as EmployeeProfile;
      if (!controller.signal.aborted) setProfile(data);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Карточка недоступна.");
    }).finally(() => { if (!controller.signal.aborted) setLoaded(true); });
    return () => controller.abort();
  }, [employeeId, readOnly]);

  function change(patch: Partial<EmployeeProfile>) {
    setProfile((value) => value ? { ...value, ...patch } : value);
    setNotice("");
  }

  async function save(status: "draft" | "submitted") {
    if (!profile || readOnly || busy) return;
    if (profile.children_birth_dates?.some((value) => !value || ageOn(value) === null)) {
      setError("Укажите дату рождения каждого ребёнка или удалите незаполненную строку.");
      return;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const { birth_date, phone, city, education, children_birth_dates, revision } = profile;
      const response = await fetch("/api/hr/me/profile", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ birth_date, phone, city, education, children_birth_dates, revision, status }),
      });
      if (!response.ok) {
        setError(response.status === 409 ? "Карточка изменена в другом окне. Обновите страницу перед сохранением."
          : response.status === 422 ? "Проверьте даты рождения: они не могут быть в будущем, а ребёнок не может быть старше родителя."
          : "Сохранение не подтверждено. Проверьте доступ и обновите страницу.");
        return;
      }
      setProfile(await response.json() as EmployeeProfile);
      setNotice(status === "submitted" ? "Карточка сохранена. HR видит, что вы её заполнили. Рабочий доступ активируется отдельно."
        : "Черновик сохранён. Вы сможете продолжить позже.");
    } catch { setError("Связь прервалась. Обновите страницу, чтобы проверить, сохранились ли данные."); }
    finally { setBusy(false); }
  }

  return <section className="w-full rounded-2xl bg-surface p-5 text-ink shadow-card sm:p-8" aria-labelledby="profile-title">
    <h2 id="profile-title" className="text-xl font-bold">{readOnly ? "Личная карточка сотрудника" : "Моя HR-карточка"}</h2>
    {!readOnly && <p className="mt-2 text-sm leading-6 text-muted">Все поля ниже необязательны. Заполняйте только те сведения, которыми хотите поделиться с HR. Руководитель видит статус заполнения.</p>}
    {!loaded && <p role="status" className="mt-4">Загружаем карточку…</p>}
    {error && <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-red-800">{error}</p>}
    {notice && <p role="status" className="mt-4 rounded-xl bg-green-50 p-3 text-green-800">{notice}</p>}
    {profile && <>
      <div className="my-5 rounded-xl bg-sunken p-4">
        <p className="font-semibold">{profile.full_name}</p>
        <p className="mt-1 text-sm text-muted">{profile.department} · {profile.position}</p>
        <p className="mt-2 text-sm">Анкета: {PROFILE_STATUSES[profile.status] ?? profile.status}</p>
        {!readOnly && <p className="mt-2 text-xs text-muted">ФИО, должность и отдел меняет HR. Если в них ошибка, сообщите ответственному сотруднику.</p>}
      </div>
      <fieldset disabled={readOnly || busy} className="space-y-5">
        <legend className="sr-only">Личные сведения</legend>
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="text-sm text-muted">Дата рождения
            <input type="date" value={profile.birth_date ?? ""} onChange={(e) => change({ birth_date: e.target.value || null })} className={inputClass} />
          </label>
          <label className="text-sm text-muted">Телефон
            <input type="tel" autoComplete="tel" maxLength={40} value={profile.phone} onChange={(e) => change({ phone: e.target.value })} className={inputClass} />
          </label>
          <label className="text-sm text-muted">Город проживания
            <input autoComplete="address-level2" maxLength={128} value={profile.city} onChange={(e) => change({ city: e.target.value })} className={inputClass} />
          </label>
          <label className="text-sm text-muted">Образование / специальность
            <input maxLength={500} value={profile.education} onChange={(e) => change({ education: e.target.value })} className={inputClass} />
          </label>
        </div>
        <div className="border-t border-line pt-5">
          <h3 className="font-semibold">Дети</h3>
          <p className="mt-1 text-sm text-muted">Имена не нужны. Возраст рассчитывается автоматически по дате рождения.</p>
          <label className="mt-3 block text-sm text-muted">Сведения о детях
            <select className={inputClass} value={profile.children_birth_dates === null ? "private" : profile.children_birth_dates.length ? "yes" : "none"}
              onChange={(e) => change({ children_birth_dates: e.target.value === "private" ? null : e.target.value === "none" ? [] : [""] })}>
              <option value="private">Не указывать</option><option value="none">Нет детей</option><option value="yes">Указать детей</option>
            </select>
          </label>
          {!!profile.children_birth_dates?.length && <p className="mt-3 text-sm">Количество детей: {profile.children_birth_dates.length}</p>}
          {profile.children_birth_dates?.map((birthday, index) => <div key={index} className="mt-3 flex flex-wrap items-end gap-3">
            <label className="min-w-0 flex-1 text-sm text-muted">Дата рождения ребёнка {index + 1}
              <input type="date" value={birthday} className={inputClass} onChange={(e) => change({ children_birth_dates: profile.children_birth_dates!.map((value, i) => i === index ? e.target.value : value) })} />
            </label>
            <span className="pb-3 text-sm">Возраст: {ageOn(birthday) ?? "—"}</span>
            {!readOnly && <button type="button" className="rounded-xl border border-line px-3 py-3 text-sm" onClick={() => change({ children_birth_dates: profile.children_birth_dates!.filter((_, i) => i !== index) })} aria-label={`Удалить ребёнка ${index + 1}`}>Удалить</button>}
          </div>)}
          {!readOnly && profile.children_birth_dates !== null && profile.children_birth_dates.length < 30 && <button type="button" className="mt-3 rounded-xl border border-line px-4 py-2 text-sm" onClick={() => change({ children_birth_dates: [...profile.children_birth_dates!, ""] })}>Добавить ребёнка</button>}
        </div>
        {!readOnly && <div className="flex flex-wrap gap-3 border-t border-line pt-5">
          <button type="button" onClick={() => void save("draft")} className="rounded-xl border border-line px-5 py-3 text-sm font-semibold">Сохранить черновик</button>
          <button type="button" onClick={() => void save("submitted")} className="rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white">{busy ? "Сохраняем…" : "Я заполнил карточку"}</button>
        </div>}
      </fieldset>
    </>}
  </section>;
}
