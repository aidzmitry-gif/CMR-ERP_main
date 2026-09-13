"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { ProcurementSourcePicker } from "./procurement-source-picker";

type Organization = { id: number; name: string; unp: string };
type Ownership = { id: number; kind: string; source_id: number; snapshot: Record<string, string | number | null>; evidence: string };
type Link = { id: number; order_ownership_id: number; request_ownership_id: number; evidence: string };
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/procurement${path}`, { method: body === undefined ? "GET" : "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(response.status === 409 ? "Данные или решение изменились. Обновите список и проверьте документ заново." : typeof data.detail === "string" ? data.detail : "Проверьте документ, основание и права доступа.");
  return data;
}
export function ProcurementOwnership() {
  const [organizations, setOrganizations] = useState<Organization[]>([]), [org, setOrg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void api<Organization[]>("/receipt-organizations").then((rows) => { if (active) setOrganizations(rows); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  return <main className="min-w-0 w-0 flex-1 space-y-4 overflow-auto p-6 lg:pr-24"><h1 className="text-2xl font-semibold">Юрлица и связи закупок</h1>
    <label>Юрлицо закупок<Select value={org} onChange={(e) => setOrg(e.target.value)}><option value="">Выберите организацию</option>{organizations.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}</Select></label>
    {error && <p role="alert">{error}</p>}{org && <OwnershipBook key={org} org={org} />}
  </main>;
}
function OwnershipBook({ org }: { org: string }) {
  const [rows, setRows] = useState<Ownership[]>([]), [links, setLinks] = useState<Link[]>([]);
  const [form, setForm] = useState({ kind: "order", source_id: "", evidence: "" });
  const [order, setOrder] = useState(""), [request, setRequest] = useState(""), [reason, setReason] = useState("");
  const [preview, setPreview] = useState<{ body: object; snapshot: Ownership["snapshot"] } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [reload, setReload] = useState(0);
  const prefix = `/organizations/${org}`;
  // Async handlers use a per-mount lifetime so a different book never receives results.
  const lifetime = useRef(true);
  useEffect(() => { lifetime.current = true; return () => { lifetime.current = false; }; }, [lifetime]);
  useEffect(() => {
    let active = true;
    void Promise.all([api<Ownership[]>(`${prefix}/purchase-ownership`), api<Link[]>(`${prefix}/order-request-links`)])
      .then(([owned, related]) => { if (active) { setRows(owned); setLinks(related); } }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [prefix, reload]);
  async function run(action: "preview" | "confirm" | "link") {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      if (action === "preview") {
        const body = { ...form, source_id: Number(form.source_id) };
        const data = await api<{ snapshot: Ownership["snapshot"] }>(`${prefix}/purchase-ownership/preview`, body);
        if (lifetime.current) setPreview({ body, snapshot: data.snapshot });
      } else if (action === "confirm" && preview) {
        const row = await api<Ownership>(`${prefix}/purchase-ownership`, { ...preview.body, expected_snapshot: preview.snapshot });
        if (lifetime.current) { setRows((old) => [row, ...old.filter((r) => r.id !== row.id)]); setPreview(null); setNotice("Юрлицо документа подтверждено."); setReload((v) => v + 1); }
      } else if (action === "link") {
        const row = await api<Link>(`${prefix}/order-request-links`, { order_id: Number(order), request_id: Number(request), evidence: reason });
        if (lifetime.current) { setLinks((old) => [row, ...old.filter((r) => r.id !== row.id)]); setNotice("Заявка связана с заказом."); setReload((v) => v + 1); }
      }
    } catch (e) { if (lifetime.current) setError((e as Error).message); }
    finally { if (lifetime.current) setBusy(false); }
  }
  const title = (id: number) => { const row = rows.find((r) => r.id === id); return row ? `${row.snapshot.number || `№ ${row.source_id}`}` : `Запись ${id}`; };
  return <div className="space-y-4">
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy} className="space-y-3 rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Подтверждение владельца документа</h2><p className="text-sm text-muted">Главный бухгалтер проверяет реквизиты и основание. Подтверждённое решение сохраняется в истории.</p>
      <label>Вид документа<Select value={form.kind} onChange={(e) => { setForm({ ...form, kind: e.target.value, source_id: "" }); setPreview(null); }}><option value="order">Заказ поставщику</option><option value="request">Заявка плана закупок</option></Select></label>
      <ProcurementSourcePicker key={`${org}/${form.kind}/${reload}`} org={org} kind={form.kind} onSelect={(id) => { setForm({ ...form, source_id: String(id) }); setPreview(null); }} />
      <label>ID документа из карточки<Input value={form.source_id} onChange={(e) => { setForm({ ...form, source_id: e.target.value }); setPreview(null); }} /></label>
      <label>Основание выбора юрлица<Input value={form.evidence} onChange={(e) => { setForm({ ...form, evidence: e.target.value }); setPreview(null); }} /></label>
      <Button disabled={!/^[1-9]\d*$/.test(form.source_id) || !form.evidence.trim()} onClick={() => void run("preview")}>Проверить документ</Button>
      {preview && <div className="rounded-lg border border-accent p-3"><p>{String(preview.snapshot.number ?? "")} · {String(preview.snapshot.supplier ?? "")}</p>{preview.snapshot.item && <p>{String(preview.snapshot.item)} · {String(preview.snapshot.quantity)}</p>}<Button onClick={() => void run("confirm")}>Подтвердить юрлицо документа</Button></div>}
    </fieldset>
    <section className="rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Подтверждённые документы</h2><ul>{rows.map((row) => <li key={row.id}>{row.kind === "order" ? "Заказ" : "Заявка"} {String(row.snapshot.number || row.source_id)} · {String(row.snapshot.supplier ?? "")} · {row.evidence}</li>)}</ul></section>
    <fieldset disabled={busy} className="space-y-3 rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Заявка → заказ поставщику</h2>
      <label>Заявка своего юрлица<Select value={request} onChange={(e) => setRequest(e.target.value)}><option value="">Выберите заявку</option>{rows.filter((r) => r.kind === "request").map((r) => <option key={r.id} value={r.source_id}>{String(r.snapshot.number || r.source_id)}</option>)}</Select></label>
      <label>Заказ своего юрлица<Select value={order} onChange={(e) => setOrder(e.target.value)}><option value="">Выберите заказ</option>{rows.filter((r) => r.kind === "order").map((r) => <option key={r.id} value={r.source_id}>{String(r.snapshot.number || r.source_id)}</option>)}</Select></label>
      <label>Основание связи<Input value={reason} onChange={(e) => setReason(e.target.value)} /></label><Button disabled={!request || !order || !reason.trim()} onClick={() => void run("link")}>Связать заявку с заказом</Button>
      <ul>{links.map((row) => <li key={row.id}>{title(row.request_ownership_id)} → {title(row.order_ownership_id)} · {row.evidence}</li>)}</ul>
    </fieldset>
  </div>;
}
