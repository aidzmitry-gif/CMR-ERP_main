"use client";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { notifyInstallationChanged } from "@/lib/installation-events";
import { InstallationSettingsError,loadInstallationSettings,saveInstallationSettings,type InstallationCommand,type InstallationSettings } from "@/lib/installation-settings";
import { useEffect,useRef,useState } from "react";

export function InstallationOrganizationSettings() {
  const [settings, setSettings] = useState<InstallationSettings | null>(null);
  const [selected, setSelected] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [stale, setStale] = useState(false);
  const pending = useRef<InstallationCommand | null>(null);
  useEffect(() => {
    let active = true;
    void loadInstallationSettings().then(value => {
      if (!active) return;
      setSettings(value); setSelected(value.organization ? String(value.organization.id) : "");
      setError(""); setStale(false); setUncertain(false); pending.current = null;
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Настройка недоступна."); });
    return () => { active = false; };
  }, [attempt]);

  async function save() {
    if (!settings?.can_manage || busy || stale || !selected) return;
    const command = pending.current ?? { organization_id: Number(selected), expected_revision: settings.revision, request_id: crypto.randomUUID() };
    pending.current = command;
    setBusy(true); setError(""); setNotice("");
    try {
      const saved = await saveInstallationSettings(command);
      setSettings({ ...settings, organization: saved.organization, revision: saved.revision, configuration: "platform_settings" });
      pending.current = null; setUncertain(false);
      setNotice(`Сохранено для всей платформы: ${saved.organization.name} · УНП ${saved.organization.unp}.`);
      notifyInstallationChanged(saved.revision);
    } catch (reason) {
      const unknown = reason instanceof InstallationSettingsError && reason.uncertain;
      setUncertain(unknown); setStale(reason instanceof InstallationSettingsError && reason.status === 409);
      if (!unknown) pending.current = null;
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить настройку.");
    } finally { setBusy(false); }
  }

  return <section className="mt-5 space-y-3 rounded-2xl bg-surface p-5 shadow-card" aria-label="Юрлицо платформы">
    <h2 className="font-semibold text-ink">Наша организация — продавец</h2>
    <p className="text-sm text-muted">Выберите юрлицо, от имени которого работает вся платформа. Оно применяется во всех разделах. Ранее оформленные документы сохраняют своё юрлицо.</p>
    {!settings && !error && <p role="status">Загрузка настройки юрлица…</p>}
    {settings && <>
      <p>{settings.organization ? `${settings.organization.name} · УНП ${settings.organization.unp}` : "Юрлицо не настроено или недоступно."}</p>
      {settings.can_manage ? <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-64 flex-1 text-sm">Юрлицо для всей платформы
          <Select aria-label="Юрлицо для всей платформы" value={selected} disabled={busy || uncertain || stale} onChange={event => { setSelected(event.target.value); setNotice(""); }}>
            <option value="">Выберите нашу организацию</option>
            {settings.organizations.map(row => <option key={row.id} value={row.id}>{row.name} · УНП {row.unp}</option>)}
          </Select>
        </label>
        <Button onClick={() => void save()} disabled={busy || stale || !selected || (!uncertain && settings.configuration === "platform_settings" && Number(selected) === settings.organization?.id)}>
          {busy ? "Сохранение…" : uncertain ? "Повторить тот же запрос" : "Сохранить для всей платформы"}
        </Button>
      </div> : <p className="text-sm text-muted">Изменение доступно администратору с правом настройки платформы и доступом к организации.</p>}
    </>}
    {error && <p role="alert" className="text-red-700">{error}{uncertain ? " Результат не подтверждён; повтор использует прежнюю команду." : ""}</p>}
    {notice && <p role="status">{notice}</p>}
    {(!settings || stale) && error && <Button variant="secondary" disabled={busy} onClick={() => { setSettings(null); setError(""); setAttempt(value => value + 1); }}>Перечитать настройку</Button>}
  </section>;
}
