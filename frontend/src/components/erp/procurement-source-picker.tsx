"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Candidate = { source_id: number; number: string; supplier: string; item: string | null };
type Page = { items: Candidate[]; next_after_id: number | null };
export function ProcurementSourcePicker({ org, kind, onSelect }: { org: string; kind: string; onSelect: (id: number) => void }) {
  const [query, setQuery] = useState(""), [page, setPage] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function search(after = 0) {
    if (busy) return;
    setBusy(true); setError(""); if (!after) setPage(null);
    try {
      const response = await fetch(`/api/procurement/organizations/${org}/purchase-ownership/candidates?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(query)}&after_id=${after}`, { cache: "no-store" });
      const data = await response.json();
      if (!active.current) return;
      if (!response.ok) throw new Error(response.status === 403 ? "Поиск документов без юрлица доступен главному бухгалтеру." : "Не удалось найти документы. Повторите поиск.");
      setPage((previous) => ({ ...data, items: after ? [...(previous?.items ?? []), ...data.items] : data.items }));
    } catch (e) { if (active.current) setError((e as Error).message); }
    finally { if (active.current) setBusy(false); }
  }
  return <fieldset disabled={busy} className="space-y-2 rounded-lg border border-line p-3"><legend>Документы без подтверждённого юрлица</legend>
    <label>Номер, поставщик или товар<Input value={query} maxLength={200} onChange={(e) => { setQuery(e.target.value); setPage(null); }} /></label>
    <Button variant="secondary" onClick={() => void search()}>Найти документы</Button>
    {error && <p role="alert">{error}</p>}
    {page && !page.items.length && <p>Документы не найдены.</p>}
    <ul>{page?.items.map((row) => <li key={row.source_id}><Button variant="secondary" onClick={() => onSelect(row.source_id)}>Выбрать {row.number || `№ ${row.source_id}`} · {row.supplier}{row.item ? ` · ${row.item}` : ""}</Button></li>)}</ul>
    {page?.next_after_id != null && <Button variant="secondary" onClick={() => void search(page.next_after_id!)}>Показать ещё</Button>}
  </fieldset>;
}
