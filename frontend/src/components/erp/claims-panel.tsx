"use client";

import clsx from "clsx";
import { Check, Plus, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  CLAIM_TYPES,
  type Claim,
  type ClaimInput,
  type ClaimStatus,
  claimCounts,
  claimStatusLabel,
  claimStatusTone,
  claimTypeLabel,
  createClaim,
  fetchClaims,
  filterClaims,
  sourceLabel,
  updateClaim,
} from "@/lib/procurement-claims";

const SEGMENTS: { id: ClaimStatus | "all"; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "open", label: "Открытые" },
  { id: "resolved", label: "Решённые" },
  { id: "rejected", label: "Отклонённые" },
];

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted">{label}</span>
      {children}
    </label>
  );
}

const INPUT_CLS =
  "mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";

export function ClaimsPanel({ initial }: { initial: Claim[] }) {
  const [claims, setClaims] = useState<Claim[]>(initial);
  const [seg, setSeg] = useState<ClaimStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // создание претензии
  const [create, setCreate] = useState<ClaimInput | null>(null);
  // урегулирование: претензия + целевой статус + текст резолюции
  const [resolve, setResolve] = useState<{ claim: Claim; status: ClaimStatus; text: string } | null>(null);

  async function refresh() {
    setClaims(await fetchClaims());
  }

  useEffect(() => {
    void fetchClaims().then(setClaims);
  }, []);

  const counts = useMemo(() => claimCounts(claims), [claims]);
  const rows = useMemo(
    () => filterClaims(claims, { status: seg, type: typeFilter, query }),
    [claims, seg, typeFilter, query],
  );

  function draftFor(c: Claim): string {
    return drafts[c.id] ?? c.supplier;
  }

  async function onSaveSupplier(c: Claim) {
    const supplier = draftFor(c).trim();
    if (supplier === c.supplier) return;
    setBusy(true);
    await updateClaim(c.id, { supplier });
    await refresh();
    setBusy(false);
  }

  async function onCreate() {
    if (!create) return;
    setBusy(true);
    setError("");
    const saved = await createClaim(create);
    setBusy(false);
    if (!saved) {
      setError("Не удалось завести претензию");
      return;
    }
    setCreate(null);
    await refresh();
  }

  async function onResolveConfirm() {
    if (!resolve) return;
    setBusy(true);
    setError("");
    const ok = await updateClaim(resolve.claim.id, { status: resolve.status, resolution: resolve.text });
    setBusy(false);
    if (!ok) {
      setError("Не удалось урегулировать претензию");
      return;
    }
    setResolve(null);
    await refresh();
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="grid grid-cols-4 gap-3">
        <Kpi label="Претензий всего" value={counts.total} />
        <Kpi label="Открыто" value={counts.open} />
        <Kpi label="Без поставщика" value={counts.withoutSupplier} />
        <Kpi label="Решено" value={counts.resolved} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="inline-flex flex-wrap rounded-lg border border-line bg-sunken p-1">
          {SEGMENTS.map((s) => (
            <button
              key={s.id}
              onClick={() => setSeg(s.id)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-medium",
                seg === s.id ? "bg-surface text-accent-ink shadow-sm" : "text-muted",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent">
          <option value="all">Все типы</option>
          {CLAIM_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <div className="relative ml-auto">
          <Search size={15} className="pointer-events-none absolute left-3 top-2.5 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по изделию, наряду, поставщику"
            className="w-72 rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-sm text-ink outline-none focus:border-accent"
          />
        </div>
        <button
          onClick={() => {
            setError("");
            setCreate({ claim_type: "брак", qty_affected: 0 });
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <Plus size={15} /> Претензия
        </button>
      </div>

      {error && <div className="mt-3 text-sm text-red-600">{error}</div>}

      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Наряд</th>
              <th className="px-4 py-2 font-medium">Изделие</th>
              <th className="px-4 py-2 font-medium">Тип</th>
              <th className="px-4 py-2 text-right font-medium">Сумма, BYN</th>
              <th className="px-4 py-2 font-medium">Источник</th>
              <th className="px-4 py-2 font-medium">Поставщик</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-muted">
                  {claims.length === 0 ? "Претензий пока нет" : "Ничего не найдено"}
                </td>
              </tr>
            )}
            {rows.map((c) => {
              const isOpen = c.status === "open";
              return (
                <tr key={c.id} className="border-b border-line align-top last:border-0">
                  <td className="px-4 py-2.5 font-medium text-muted">{c.order_code || "—"}</td>
                  <td className="px-4 py-2.5 text-muted">{c.item}</td>
                  <td className="px-4 py-2.5 text-muted">{claimTypeLabel(c.claim_type)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                    {c.amount_byn == null ? "—" : c.amount_byn.toLocaleString("ru-RU")}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex rounded-md bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600 dark:bg-red-500/10 dark:text-red-300">
                      {sourceLabel(c.source)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    {isOpen ? (
                      <input
                        value={draftFor(c)}
                        onChange={(e) => setDrafts((d) => ({ ...d, [c.id]: e.target.value }))}
                        onBlur={() => onSaveSupplier(c)}
                        placeholder="Назначить…"
                        className="w-40 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                      />
                    ) : (
                      <span className="text-muted">{c.supplier || "—"}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium", claimStatusTone(c.status))}>
                      {claimStatusLabel(c.status)}
                    </span>
                    {c.resolution && <div className="mt-0.5 text-[11px] text-faint">{c.resolution}</div>}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      {isOpen && (
                        <>
                          <button
                            onClick={() => setResolve({ claim: c, status: "resolved", text: "" })}
                            disabled={busy}
                            title="Урегулировать (решена)"
                            className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-green-50 hover:text-green-600 disabled:opacity-60"
                          >
                            <Check size={15} />
                          </button>
                          <button
                            onClick={() => setResolve({ claim: c, status: "rejected", text: "" })}
                            disabled={busy}
                            title="Отклонить претензию"
                            className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-muted disabled:opacity-60"
                          >
                            <X size={15} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">
        Претензия открывается автоматически при браке в ОТК производства или вручную закупщиком.
        Назначьте поставщика и закройте решением/отклонением — при закрытии эмитится событие для финансов/качества.
      </p>

      {/* Drawer создания претензии */}
      {create && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setCreate(null)}>
          <div className="h-full w-full max-w-md overflow-auto bg-canvas p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-ink">Новая претензия</h2>
              <button onClick={() => setCreate(null)} className="text-muted hover:text-ink">
                <X size={18} />
              </button>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3">
              <Field label="Изделие">
                <input value={create.item ?? ""} onChange={(e) => setCreate({ ...create, item: e.target.value })} className={INPUT_CLS} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Тип">
                  <select value={create.claim_type ?? "брак"} onChange={(e) => setCreate({ ...create, claim_type: e.target.value })} className={INPUT_CLS}>
                    {CLAIM_TYPES.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Кол-во">
                  <input type="number" value={String(create.qty_affected ?? 0)} onChange={(e) => setCreate({ ...create, qty_affected: Number(e.target.value) || 0 })} className={INPUT_CLS} />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Поставщик">
                  <input value={create.supplier ?? ""} onChange={(e) => setCreate({ ...create, supplier: e.target.value })} className={INPUT_CLS} />
                </Field>
                <Field label="Сумма, BYN">
                  <input type="number" value={create.amount_byn == null ? "" : String(create.amount_byn)} onChange={(e) => setCreate({ ...create, amount_byn: e.target.value.trim() === "" ? null : Number(e.target.value) || 0 })} className={INPUT_CLS} />
                </Field>
              </div>
              <Field label="Наряд / заказ">
                <input value={create.order_code ?? ""} onChange={(e) => setCreate({ ...create, order_code: e.target.value })} className={INPUT_CLS} />
              </Field>
              <Field label="Причина">
                <input value={create.reason ?? ""} onChange={(e) => setCreate({ ...create, reason: e.target.value })} className={INPUT_CLS} />
              </Field>
            </div>
            <div className="mt-5 flex gap-2">
              <button onClick={onCreate} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
                {busy ? "Сохранение…" : "Завести"}
              </button>
              <button onClick={() => setCreate(null)} className="rounded-lg border border-line bg-surface px-4 py-2 text-sm font-medium text-muted hover:bg-sunken">
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Drawer урегулирования */}
      {resolve && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setResolve(null)}>
          <div className="h-full w-full max-w-md overflow-auto bg-canvas p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-ink">
                {resolve.status === "resolved" ? "Урегулировать претензию" : "Отклонить претензию"}
              </h2>
              <button onClick={() => setResolve(null)} className="text-muted hover:text-ink">
                <X size={18} />
              </button>
            </div>
            <p className="mt-2 text-sm text-muted">{resolve.claim.item} · {claimTypeLabel(resolve.claim.claim_type)}</p>
            <Field label="Как урегулировано (резолюция)">
              <textarea
                value={resolve.text}
                onChange={(e) => setResolve({ ...resolve, text: e.target.value })}
                rows={4}
                className={INPUT_CLS}
                placeholder="Поставщик компенсировал… / допоставил… / отклонено, т.к…"
              />
            </Field>
            <div className="mt-5 flex gap-2">
              <button onClick={onResolveConfirm} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
                {busy ? "Сохранение…" : resolve.status === "resolved" ? "Решено" : "Отклонить"}
              </button>
              <button onClick={() => setResolve(null)} className="rounded-lg border border-line bg-surface px-4 py-2 text-sm font-medium text-muted hover:bg-sunken">
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
