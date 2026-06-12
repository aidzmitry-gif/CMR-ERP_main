"use client";

import clsx from "clsx";
import { Check, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  type Claim,
  type ClaimStatus,
  claimCounts,
  claimStatusLabel,
  claimStatusTone,
  fetchClaims,
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
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

export function ClaimsPanel({ initial }: { initial: Claim[] }) {
  const [claims, setClaims] = useState<Claim[]>(initial);
  const [seg, setSeg] = useState<ClaimStatus | "all">("all");
  const [query, setQuery] = useState("");
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setClaims(await fetchClaims());
  }

  useEffect(() => {
    // первичные данные пришли с SSR; тихо перечитываем на клиенте
    void refresh();
  }, []);

  const counts = useMemo(() => claimCounts(claims), [claims]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return claims.filter((c) => {
      if (seg !== "all" && c.status !== seg) return false;
      if (!q) return true;
      return (
        c.item.toLowerCase().includes(q) ||
        c.order_code.toLowerCase().includes(q) ||
        c.supplier.toLowerCase().includes(q)
      );
    });
  }, [claims, seg, query]);

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

  async function onStatus(c: Claim, status: ClaimStatus) {
    setBusy(true);
    await updateClaim(c.id, { status });
    await refresh();
    setBusy(false);
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
        <div className="inline-flex flex-wrap rounded-lg border border-slate-200 bg-slate-50 p-1">
          {SEGMENTS.map((s) => (
            <button
              key={s.id}
              onClick={() => setSeg(s.id)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-medium",
                seg === s.id ? "bg-white text-brand shadow-sm" : "text-slate-500",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="relative ml-auto">
          <Search size={15} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по изделию, наряду, поставщику"
            className="w-72 rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none focus:border-brand"
          />
        </div>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Наряд</th>
              <th className="px-4 py-2 font-medium">Изделие</th>
              <th className="px-4 py-2 font-medium">Причина</th>
              <th className="px-4 py-2 font-medium">Источник</th>
              <th className="px-4 py-2 font-medium">Поставщик</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  {claims.length === 0 ? "Претензий пока нет" : "Ничего не найдено"}
                </td>
              </tr>
            )}
            {rows.map((c) => {
              const isOpen = c.status === "open";
              return (
                <tr key={c.id} className="border-b border-slate-50 last:border-0 align-top">
                  <td className="px-4 py-2.5 font-medium text-slate-700">{c.order_code || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-700">{c.item}</td>
                  <td className="px-4 py-2.5 text-slate-600">{c.reason || "—"}</td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex rounded-md bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600">
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
                        className="w-40 rounded-lg border border-slate-200 px-2 py-1.5 text-sm outline-none focus:border-brand"
                      />
                    ) : (
                      <span className="text-slate-600">{c.supplier || "—"}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={clsx(
                        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                        claimStatusTone(c.status),
                      )}
                    >
                      {claimStatusLabel(c.status)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      {isOpen && (
                        <>
                          <button
                            onClick={() => onStatus(c, "resolved")}
                            disabled={busy}
                            title="Отметить решённой"
                            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-green-50 hover:text-green-600 disabled:opacity-60"
                          >
                            <Check size={15} />
                          </button>
                          <button
                            onClick={() => onStatus(c, "rejected")}
                            disabled={busy}
                            title="Отклонить претензию"
                            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:opacity-60"
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
        Претензия открывается автоматически при браке в ОТК производства. Назначьте поставщика
        (привязка к поставке) и закройте претензию решением или отклонением.
      </p>
    </div>
  );
}
