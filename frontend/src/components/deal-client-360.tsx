import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { fetchCounterpartyCardResult, type CounterpartyCard } from "@/lib/reference-data";
import { backendAuthHeaders } from "@/lib/auth-headers-server";

const SOURCE_LABEL: Record<string, string> = { "1c": "1С", bitrix: "Bitrix", erp: "ERP", egr: "ЕГР" };

/** Досье однозначного контрагента, уже разрешённого сервером в карточке сделки. */
export async function DealClient360({ counterpartyId, roles }: { counterpartyId?: number; roles?: string }) {
  const result = counterpartyId == null ? null
    : await fetchCounterpartyCardResult(counterpartyId, roles, await backendAuthHeaders(roles));
  const card = result?.status === "success" ? result.card : null;
  const error = result?.status === "unauthorized"
    ? "Для просмотра досье клиента войдите снова."
    : result?.status === "forbidden" ? "Нет доступа к досье клиента."
    : result?.status === "service-error" || result?.status === "invalid-id"
      ? "Не удалось загрузить досье клиента. Обновите страницу." : null;
  return (
    <Card className="px-[18px] py-[14px]">
      <CardHeader>
        <span aria-hidden>🪪</span>
        <span>Клиент · 360°</span>
      </CardHeader>
      <CardBody className="space-y-2.5">{card ? <Body card={card} /> : error ? <p role="alert" className="text-sm text-muted">{error}</p> : <Empty />}</CardBody>
    </Card>
  );
}

function Empty() {
  return (
    <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
      Досье клиента пока недоступно.
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[10.5px] font-semibold text-muted">
      {children}
    </span>
  );
}

function Body({ card }: { card: CounterpartyCard }) {
  const sources = [...new Set(card.aliases.map((a) => a.source))];
  const primary = card.contacts.find((c) => c.is_primary) ?? card.contacts[0];
  const ts = card.touch_summary;
  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-muted">УНП</span>
        <span className="rounded bg-sunken px-1.5 py-0.5 text-[12px] font-semibold tabular-nums text-ink">
          {card.unp || "—"}
        </span>
        {!card.is_active && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-amber-700">
            неактивен
          </span>
        )}
        {card.merged_into_id != null && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-amber-700">
            слит
          </span>
        )}
      </div>

      {sources.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted">источники</span>
          {sources.map((s) => (
            <Chip key={s}>{SOURCE_LABEL[s] ?? s}</Chip>
          ))}
        </div>
      )}

      {primary && (
        <div className="text-[12px] text-muted">
          <span aria-hidden>👤</span> <span className="text-ink">{primary.full_name}</span>
          {primary.phone && <span> · {primary.phone}</span>}
        </div>
      )}

      {ts && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted">
          <span>📞 {ts.calls} зв.</span>
          <span>🤝 {ts.deals} сд.</span>
          <span>💬 {ts.messages} сообщ.</span>
          {ts.last_contact && <span>· посл. контакт {ts.last_contact.slice(0, 10)}</span>}
        </div>
      )}
    </>
  );
}
