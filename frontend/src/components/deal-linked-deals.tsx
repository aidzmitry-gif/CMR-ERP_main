import Link from "next/link";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Money } from "@/components/money";
import { fetchBoardStages } from "@/lib/api";

/**
 * «Сделки клиента» — другие сделки того же контрагента (матч по имени контрагента, как на
 * бэке `_counterparty_for_deal`). Чисто фронт: берёт доску и фильтрует по `company` ===
 * текущему, исключая саму сделку. Полная история клиента (вкл. выигранные/проигранные).
 * Honest-empty, если других нет. Позже `counterparty.id` в DealDetail заменит матч-по-имени.
 */
export async function DealLinkedDeals({
  company,
  currentId,
  roles,
}: {
  company: string;
  currentId: string;
  roles?: string;
}) {
  const stages = company?.trim() ? await fetchBoardStages(roles) : [];
  const others = stages
    .flatMap((s) => s.deals.map((d) => ({ d, stage: s.title })))
    .filter(({ d }) => d.company === company && d.id !== currentId);

  return (
    <Card className="px-[18px] py-[14px]">
      <CardHeader>
        <span aria-hidden>🔗</span>
        <span>
          Сделки клиента{" "}
          {others.length > 0 && <span className="font-normal text-muted">({others.length})</span>}
        </span>
      </CardHeader>
      <CardBody>
        {others.length === 0 ? (
          <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
            <span className="font-semibold text-faint">нет данных · </span>
            других сделок этого контрагента нет.
          </div>
        ) : (
          <ul className="space-y-1">
            {others.map(({ d, stage }) => (
              <li key={d.id}>
                <Link
                  href={`/crm/deals/${d.id}`}
                  className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-sunken"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[12.5px] font-semibold text-ink">
                      {d.description || d.number}
                    </span>
                    <span className="block text-[11px] text-muted">
                      {d.number} · {stage}
                    </span>
                  </span>
                  <span className="shrink-0 text-[12.5px] font-semibold tabular-nums text-ink">
                    <Money byn={d.amount} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
