"use client";

import { GitMerge } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import {
  type DuplicateCluster,
  type DuplicateMember,
  mergeCounterparties,
  totalDuplicates,
} from "@/lib/reference-data";
import { clusterDuplicates, clusterSurvivor } from "@/lib/spravochniki-merge";

function cpId(id: number) {
  return `CP-${String(id).padStart(6, "0")}`;
}

function ClusterCard({
  cluster,
  isActive,
  onSelect,
}: {
  cluster: DuplicateCluster;
  isActive: boolean;
  onSelect: () => void;
}) {
  const sv = clusterSurvivor(cluster);
  const dups = clusterDuplicates(cluster);
  return (
    <div
      className={`rounded-xl p-3 ${
        isActive ? "ring-2 ring-brand bg-brand-100/30" : "ring-1 ring-slate-200 bg-white"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
          100% · УНП
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
          {dups.length} дубл.
        </span>
      </div>
      {sv && <div className="mt-2 text-sm font-semibold text-ink">{sv.name}</div>}
      <div className="mt-1 space-y-0.5 text-[12px] text-slate-500">
        {sv && (
          <div>
            <span className="font-mono text-[13px]">{cpId(sv.id)}</span> · ★ эталон
          </div>
        )}
        {dups.map((d) => (
          <div key={d.id}>
            <span className="font-mono text-[13px]">{cpId(d.id)}</span> · дубль
          </div>
        ))}
      </div>
      <button
        className="mt-3 w-full rounded-xl bg-white px-3 py-2 text-sm font-medium text-slate-600 shadow-card ring-1 ring-slate-200 hover:bg-slate-50"
        onClick={onSelect}
      >
        Разобрать
      </button>
    </div>
  );
}

function MemberRow({
  member,
  unp,
  isSurvivor,
  busy,
  pending,
  onMerge,
}: {
  member: DuplicateMember;
  unp: string;
  isSurvivor: boolean;
  busy: boolean;
  pending: boolean;
  onMerge?: () => void;
}) {
  return (
    <tr className="hover:bg-slate-50/60">
      <td className="px-3 py-2.5 font-mono text-[13px] text-slate-500">{cpId(member.id)}</td>
      <td className="px-3 py-2.5">{member.name}</td>
      <td className="px-3 py-2.5 font-mono text-[13px] text-slate-500">{unp}</td>
      <td className="px-3 py-2.5">
        {isSurvivor ? (
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
            ★ эталон
          </span>
        ) : (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
            дубль
          </span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {/* В кластере дубли ещё НЕ слиты (приходят из duplicate_clusters, фильтр
            is_active) — расклеивать нечего, поэтому здесь только «Слить».
            Обратное действие (unmerge) живёт на карточке эталона. */}
        {!isSurvivor && (
          <button
            disabled={busy || pending}
            onClick={onMerge}
            className="flex items-center gap-1 rounded-xl bg-brand px-2.5 py-1.5 text-[12px] font-semibold text-white shadow-card disabled:opacity-50 hover:bg-brand-700"
          >
            <GitMerge size={13} />
            Слить
          </button>
        )}
      </td>
    </tr>
  );
}

export function SpravMerge({ initial }: { initial: DuplicateCluster[] }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [selected, setSelected] = useState<DuplicateCluster | null>(initial[0] ?? null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const total = totalDuplicates(initial);
  const survivor = selected ? clusterSurvivor(selected) : undefined;
  const duplicates = selected ? clusterDuplicates(selected) : [];

  async function handleMerge(dup: DuplicateMember) {
    if (!survivor) return;
    setBusyId(dup.id);
    await mergeCounterparties(survivor.id, dup.id);
    setBusyId(null);
    startTransition(() => router.refresh());
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-ink">Дедупликация — слияние дублей</h1>
        <p className="mt-1 text-sm text-muted">
          Единая эталонная запись (golden record), слияние обратимо.
        </p>
      </div>

      <div className="rounded-2xl bg-brand-100/60 px-4 py-2.5 text-[12px] text-slate-700">
        Правила:{" "}
        <span className="font-semibold">УНП совпал</span> → авто-кандидат ·{" "}
        <span className="font-semibold">имя+адрес похожи</span> → на проверку человеком · слияние
        обратимо (unmerge) · исходники сохраняются как алиасы.
      </div>

      {initial.length === 0 ? (
        <div className="rounded-2xl bg-white p-10 text-center shadow-card">
          <p className="text-muted">Дублей не обнаружено.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Левая колонка: список кластеров */}
          <div className="lg:col-span-1">
            <div className="rounded-2xl bg-white p-5 shadow-card">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Кандидаты на слияние ({total})
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                  очередь
                </span>
              </div>
              <div className="mt-3 space-y-3">
                {initial.map((cluster) => (
                  <ClusterCard
                    key={cluster.unp}
                    cluster={cluster}
                    isActive={selected?.unp === cluster.unp}
                    onSelect={() => setSelected(cluster)}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Правая колонка: разбор кластера */}
          <div className="space-y-4 lg:col-span-2">
            {selected && survivor ? (
              <>
                <div className="rounded-2xl bg-white p-5 shadow-card">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                        Разбор кластера · УНП {selected.unp}
                      </div>
                      <div className="mt-1 text-base font-semibold text-ink">{survivor.name}</div>
                    </div>
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
                      100% · УНП
                    </span>
                  </div>

                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-y border-slate-100 bg-slate-50/60 text-left text-[11px] uppercase tracking-wide text-slate-400">
                          <th className="px-3 py-2 font-semibold">Запись</th>
                          <th className="px-3 py-2 font-semibold">Наименование</th>
                          <th className="px-3 py-2 font-semibold">УНП</th>
                          <th className="px-3 py-2 font-semibold">Роль</th>
                          <th className="px-3 py-2 font-semibold">Действие</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-50">
                        <MemberRow
                          member={survivor}
                          unp={selected.unp}
                          isSurvivor
                          busy={false}
                          pending={isPending}
                        />
                        {duplicates.map((dup) => (
                          <MemberRow
                            key={dup.id}
                            member={dup}
                            unp={selected.unp}
                            isSurvivor={false}
                            busy={busyId === dup.id}
                            pending={isPending}
                            onMerge={() => handleMerge(dup)}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="mt-4 rounded-xl bg-slate-50 p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                      Правило выживания (survivorship)
                    </div>
                    <p className="mt-1 text-[13px] text-slate-600">
                      при конфликте —{" "}
                      <span className="font-semibold">непустое</span> &gt;{" "}
                      <span className="font-semibold">более свежее</span> &gt;{" "}
                      <span className="font-semibold">из приоритетного источника</span>{" "}
                      <span className="font-mono text-[12px] text-slate-500">
                        (ERP &gt; 1С &gt; Bitrix)
                      </span>
                      .
                    </p>
                  </div>

                  <div className="mt-4 flex items-center justify-end">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                      ↶ слияние обратимо (unmerge)
                    </span>
                  </div>
                </div>

                {/* Карточка движка */}
                <div className="rounded-2xl bg-ink p-5 text-slate-300 shadow-card">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                    Как решает движок
                  </div>
                  <pre className="mt-3 overflow-x-auto rounded-xl bg-black/30 p-3 text-[12px] leading-relaxed text-slate-200">
                    {[
                      `rule  unp_exact       : unp(A) == unp(B)              -> score 1.00 -> auto_merge_candidate`,
                      `rule  name_city_fuzzy : trigram(name) > 0.80 AND city -> score 0.87 -> manual_review`,
                      ``,
                      `survivorship: pick(non_empty) > pick(most_recent) > pick(source_priority: ERP > 1C > Bitrix)`,
                      `result:       golden_record(${cpId(survivor.id)}); merge_reversible = true`,
                    ].join("\n")}
                  </pre>
                  <p className="mt-3 text-[12px] text-slate-400">
                    Детерминированные ключи (УНП) — автоматически; нечёткое имя — ML-скоринг,
                    итог подтверждает человек.
                  </p>
                </div>
              </>
            ) : (
              <div className="rounded-2xl bg-white p-10 text-center shadow-card">
                <p className="text-muted">Выберите кластер для разбора.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
