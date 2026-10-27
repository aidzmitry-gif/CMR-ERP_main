"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { loadCounterpartyRelationships, type RelationshipPage, type RelationshipResult } from "@/lib/counterparty-relationships";

const PAGE_SIZE = 20;

export function DealLinkedDeals({ counterpartyId, currentId }: {
  counterpartyId?: number;
  currentId: string;
}) {
  const parsedCurrentId = /^[1-9]\d*$/.test(currentId) ? Number(currentId) : NaN;
  const currentDealId = Number.isSafeInteger(parsedCurrentId) ? parsedCurrentId : null;
  const hasIdentity = Number.isSafeInteger(counterpartyId) && (counterpartyId ?? 0) > 0 && currentDealId !== null;
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState<{
    counterpartyId: number;
    currentDealId: number;
    offset: number;
    revision: number;
    result: RelationshipResult;
  } | null>(null);
  const matchesCurrent = loaded !== null && loaded.counterpartyId === counterpartyId
    && loaded.currentDealId === currentDealId && loaded.offset === offset && loaded.revision === revision;
  const result = matchesCurrent ? loaded.result : null;
  const page: Extract<RelationshipPage, { kind: "deals" }> | null = result?.status === "ok" && result.page.kind === "deals"
    ? result.page : null;

  useEffect(() => {
    if (!hasIdentity || counterpartyId == null || currentDealId == null) return;
    const controller = new AbortController();
    void loadCounterpartyRelationships(counterpartyId, "deals", offset, undefined, controller.signal).then((next) => {
      if (!controller.signal.aborted) setLoaded({ counterpartyId, currentDealId, offset, revision, result: next });
    });
    return () => controller.abort();
  }, [counterpartyId, currentDealId, hasIdentity, offset, revision]);

  const others = page?.items.filter((deal) => deal.id !== currentDealId) ?? [];
  const error = result?.status === "forbidden" ? "Нет доступа к связанным сделкам."
    : result?.status === "unauthorized" ? "Сессия истекла. Войдите в систему."
      : result?.status === "error" ? "Не удалось загрузить связанные сделки."
        : null;

  function retry() {
    setLoaded(null);
    setRevision((value) => value + 1);
  }

  const hasNext = page !== null && offset + page.limit < page.total;
  const hasPrevious = offset > 0;

  return (
    <Card className="px-[18px] py-[14px]">
      <CardHeader><span aria-hidden="true">🔗</span><span>Сделки клиента</span></CardHeader>
      <CardBody>
        {!hasIdentity ? (
          <p className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
            Контрагент не связан с этой сделкой по точному ID.
          </p>
        ) : !result ? (
          <p role="status" className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
            Загрузка связанных сделок…
          </p>
        ) : error ? (
          <div role="alert" className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
            {error} <button type="button" className="underline" onClick={retry}>Повторить</button>
          </div>
        ) : page && others.length > 0 ? (
          <>
            <p className="mb-2 text-[11px] text-muted">Связь определена по точному ID; текущая сделка скрыта.</p>
            <ul className="space-y-1">
              {others.map((deal) => (
                <li key={deal.id}>
                  <Link href={`/crm/deals/${deal.id}`} className="block rounded-lg px-2 py-1.5 hover:bg-sunken">
                    <span className="block truncate text-[12.5px] font-semibold text-ink">
                      {deal.number} — {deal.title}
                    </span>
                    <span className="block text-[11px] text-muted">Стадия: {deal.stage}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : page?.total === 0 ? (
          <p className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
            Связанных сделок по точному ID не найдено.
          </p>
        ) : page?.items.some((deal) => deal.id === currentDealId) && page.total === 1 ? (
          <p className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
            Других сделок по этому контрагенту нет.
          </p>
        ) : (
          <p className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
            На этой странице других сделок нет.
          </p>
        )}
        {page && (page.total > PAGE_SIZE || offset > 0) && (
          <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-2 text-xs text-muted">
            <span>Страница {Math.floor(offset / PAGE_SIZE) + 1} из {Math.ceil(page.total / PAGE_SIZE)}</span>
            <div className="flex gap-2">
              <button type="button" className="underline disabled:opacity-40" disabled={!hasPrevious}
                onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}>Назад</button>
              <button type="button" className="underline disabled:opacity-40" disabled={!hasNext}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}>Далее</button>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
