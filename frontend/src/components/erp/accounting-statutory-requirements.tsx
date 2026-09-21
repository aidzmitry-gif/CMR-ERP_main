"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createStatutoryRequirement, fetchStatutoryRequirements, StatutoryRequirementError, statutoryRequirementKey, validStatutoryRequirement, type RequirementKind, type StatutoryRequirement, type StatutoryRequirementRequest } from "@/lib/statutory-requirements-api";

type Props = { org: string; month: string; disabled: boolean; onBusyChange?: (busy: boolean) => void };
const blank = () => ({ code: "", title: "", source_reference: "", evidence: "", form_version: "", electronic_format_version: "", rate_value: "", rate_unit: "", rate_basis: "" });

export function AccountingStatutoryRequirements({ org, month, disabled, onBusyChange }: Props) {
  const [kind, setKind] = useState<RequirementKind>("form"), [form, setForm] = useState(blank());
  const [rows, setRows] = useState<StatutoryRequirement[] | null>(null), [loading, setLoading] = useState(false);
  const [pending, setPending] = useState<StatutoryRequirementRequest | null>(null), [saved, setSaved] = useState<StatutoryRequirement | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [saving, setSaving] = useState(false);
  const generation = useRef(0);
  const posting = useRef(false);
  const ready = !!org && /^\d{4}-\d{2}$/.test(month);

  async function load(token = generation.current) {
    if (!ready) return;
    setLoading(true); setError("");
    try { const next = await fetchStatutoryRequirements(org, month); if (token === generation.current) setRows(next); }
    catch (e) { if (token === generation.current) { setRows(null); setError(e instanceof Error ? e.message : "Каталог не загружен."); } }
    finally { if (token === generation.current) setLoading(false); }
  }
  useEffect(() => { const token = ++generation.current; posting.current = false; setRows(null); setPending(null); setSaved(null); setForm(blank()); setError(""); setNotice(""); setSaving(false); void load(token); return () => { generation.current += 1; }; }, [org, month]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { onBusyChange?.(saving); return () => onBusyChange?.(false); }, [saving, onBusyChange]);

  function build(): StatutoryRequirementRequest {
    return kind === "form"
      ? { request_key: statutoryRequirementKey(), kind, code: form.code.trim(), title: form.title.trim(), effective_from: `${month}-01`, source_reference: form.source_reference.trim(), evidence: form.evidence.trim(), form_version: form.form_version.trim(), electronic_format_version: form.electronic_format_version.trim(), rate_value: null, rate_unit: null, rate_basis: null }
      : { request_key: statutoryRequirementKey(), kind, code: form.code.trim(), title: form.title.trim(), effective_from: `${month}-01`, source_reference: form.source_reference.trim(), evidence: form.evidence.trim(), form_version: null, electronic_format_version: null, rate_value: form.rate_value.trim(), rate_unit: form.rate_unit.trim(), rate_basis: form.rate_basis.trim() };
  }
  async function submit() {
    if (!ready || disabled || posting.current) return;
    let body = pending;
    const token = generation.current;
    try { if (!body) { body = build(); if (!validStatutoryRequirement(body)) { setError("Заполните код, наименование, источник, основание и поля выбранного типа."); return; } setPending(body); } posting.current = true; setSaving(true); setError(""); setNotice(""); const result = await createStatutoryRequirement(org, body); if (token !== generation.current) return; setSaved(result); setPending(null); setRows((current) => [...(current || []).filter((row) => row.kind !== result.kind || row.code !== result.code), result]); }
    catch (e) { if (token !== generation.current) return; const known = e instanceof StatutoryRequirementError && e.status !== undefined && e.status < 500; setError(e instanceof Error ? e.message : "Версия не сохранена."); if (known) { setPending(null); setNotice(""); } else setNotice("Запрос сохранён; повторите его без изменения полей."); }
    finally { if (token === generation.current) { posting.current = false; setSaving(false); } }
  }
  const locked = disabled || loading || saving || !!pending;
  if (!ready) return <section className="rounded-lg border border-line p-3" aria-label="Каталог регламентированных требований"><p role="status">Выберите организацию и период, чтобы открыть каталог.</p></section>;
  return <section className="space-y-3 rounded-lg border border-line p-3" aria-label="Каталог регламентированных требований">
    <h3 className="font-semibold">Каталог внешних форм и ставок</h3><p className="text-sm text-muted">Период действия: {month}. Это только явная конфигурация: каталог не рассчитывает зарплату, не создаёт проводки, не сертифицирует и не отправляет отчёты.</p>
    <div className="flex gap-2"><Button variant={kind === "form" ? "primary" : "secondary"} disabled={locked} onClick={() => { setKind("form"); setForm(blank()); }}>Форма</Button><Button variant={kind === "rate" ? "primary" : "secondary"} disabled={locked} onClick={() => { setKind("rate"); setForm(blank()); }}>Ставка</Button></div>
    <div className="grid gap-2 md:grid-cols-2"><Input aria-label="Код требования" value={form.code} disabled={locked} onChange={(e) => setForm({ ...form, code: e.target.value })} /><Input aria-label="Наименование требования" value={form.title} disabled={locked} onChange={(e) => setForm({ ...form, title: e.target.value })} /><Input aria-label="Первичный источник требования" value={form.source_reference} disabled={locked} onChange={(e) => setForm({ ...form, source_reference: e.target.value })} /><Input aria-label="Основание требования" value={form.evidence} disabled={locked} onChange={(e) => setForm({ ...form, evidence: e.target.value })} />
      {kind === "form" ? <><Input aria-label="Версия формы" value={form.form_version} disabled={locked} onChange={(e) => setForm({ ...form, form_version: e.target.value })} /><Input aria-label="Версия электронного формата" value={form.electronic_format_version} disabled={locked} onChange={(e) => setForm({ ...form, electronic_format_version: e.target.value })} /></> : <><Input aria-label="Значение ставки" value={form.rate_value} disabled={locked} onChange={(e) => setForm({ ...form, rate_value: e.target.value })} /><Input aria-label="Единица ставки" value={form.rate_unit} disabled={locked} onChange={(e) => setForm({ ...form, rate_unit: e.target.value })} /><Input aria-label="База ставки" value={form.rate_basis} disabled={locked} onChange={(e) => setForm({ ...form, rate_basis: e.target.value })} /></>}</div>
    <Button disabled={disabled || loading || saving} onClick={() => void submit()}>{pending ? "Повторить сохранённый запрос" : "Сохранить версию требования"}</Button>{error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{saved && <p role="status">Версия {saved.revision} сохранена.</p>}
    <div><p className="font-semibold">Действует в выбранном периоде</p>{rows === null ? <p role="status">Загрузка…</p> : rows.length ? <ul>{rows.map((row) => <li key={row.requirement_id}>{row.kind === "form" ? "Форма" : "Ставка"}: {row.code} · версия {row.revision}</li>)}</ul> : <p>Для выбранного юрлица и периода записей нет.</p>}</div>
  </section>;
}
