import { Phone } from "lucide-react";
import Link from "next/link";
import { Card, CardBody } from "@/components/ui/card";
import { fetchDealCalls, type CallRow } from "@/lib/api";

function fmtWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    ringing: "звонит",
    answered: "ответ",
    ended: "завершён",
    missed: "пропущен",
    busy: "занято",
    failed: "сбой",
  };
  return map[status] ?? status;
}

function CallLine({ call, dealId }: { call: CallRow; dealId: string }) {
  const dir = call.direction === "out" ? "Исх." : "Вх.";
  const dur =
    call.duration_sec != null && call.duration_sec > 0
      ? `${Math.floor(call.duration_sec / 60)}:${String(call.duration_sec % 60).padStart(2, "0")}`
      : null;
  return (
    <li className="rounded-[10px] bg-sunken px-3 py-2.5 text-[12.5px]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold text-ink">
          {dir} {call.phone_e164 || "—"}
        </span>
        <span className="tabular-nums text-muted">{fmtWhen(call.started_at)}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11.5px] text-muted">
        <span>{statusLabel(call.status)}</span>
        {dur && <span>· {dur}</span>}
        {call.result && <span>· {call.result}</span>}
      </div>
      {call.recording_url && (
        <a
          href={call.recording_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-block text-[11.5px] font-semibold text-accent-ink hover:underline"
        >
          Запись разговора
        </a>
      )}
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px]">
        <Link className="underline" href={`/crm/calls?call_id=${call.id}#call-${call.id}`}>Открыть звонок</Link>
        {call.crm_client_id != null && <Link className="underline" href={`/crm/clients/${call.crm_client_id}`}>CRM-клиент</Link>}
        {call.counterparty_id != null && <Link className="underline" href={`/erp/spravochniki/counterparty/${call.counterparty_id}`}>Компания</Link>}
        {call.contact_id != null && call.counterparty_id != null && <Link className="underline" href={`/erp/spravochniki/counterparty/${call.counterparty_id}?contact=${call.contact_id}#counterparty-contact-${call.contact_id}`}>Контакт</Link>}
        <Link className="underline" href={`/crm/deals/${dealId}`}>Сделка</Link>
      </div>
    </li>
  );
}

/** Лента звонков сделки (zruchna → CallLog с deal_id открытой сделки). */
export async function DealCalls({
  dealId,
  roles,
  accessToken,
}: {
  dealId: string;
  roles?: string;
  accessToken?: string;
}) {
  const calls = await fetchDealCalls(dealId, roles, accessToken);
  return (
    <Card>
      <div className="flex items-center gap-2 border-b border-line px-[14px] py-2.5 text-[13px] font-bold text-ink">
        <Phone size={14} className="text-muted" />
        Звонки
        {calls.length > 0 && (
          <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11px] font-semibold text-muted">
            {calls.length}
          </span>
        )}
      </div>
      <CardBody className="space-y-2">
        {calls.length === 0 ? (
          <div className="text-[12.5px] text-muted">
            Пока нет звонков по этой сделке. Входящие с АТС попадают сюда, если у клиента есть
            открытая сделка в воронке; история клиента — всегда в карточке контрагента.
          </div>
        ) : (
          <ul className="space-y-2">
            {calls.map((c) => (
              <CallLine key={c.id} call={c} dealId={dealId} />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
