import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { fetchCounterpartyCard, type CounterpartyCard } from "@/lib/reference-data";

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";
const SOURCE_LABEL: Record<string, string> = { "1c": "1С", bitrix: "Bitrix", erp: "ERP", egr: "ЕГР" };

/** Резолв контрагента сделки (free-text имя) в MDM по имени → id эталона (или null). */
async function resolveId(company: string, roles?: string): Promise<number | null> {
  try {
    const res = await fetch(`${BASE}/system/references/query`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(roles ? { "X-User-Roles": roles } : {}) },
      body: JSON.stringify({ ref: "core.counterparties", name: company, limit: 1 }),
    });
    if (!res.ok) return null;
    const rows = ((await res.json())?.result ?? []) as { id: number }[];
    return rows[0]?.id ?? null;
  } catch {
    return null;
  }
}

/**
 * Мини-досье 360° по контрагенту сделки (SSR). Резолвит компанию в MDM по имени и
 * показывает golden record: УНП, источники (1С/Bitrix/ЕГР — единая личность клиента из
 * синхронизированных систем), первичный контакт и сводку касаний. Honest-empty, если в MDM
 * нет совпадения — контрагентов 1С грузит сессия Справочников, досье «оживёт» по мере загрузки.
 * Читает только core-эндпоинты (`/system/references/query`, `/system/mdm/counterparty/{id}`).
 */
export async function DealClient360({ company, roles }: { company: string; roles?: string }) {
  const id = company?.trim() ? await resolveId(company, roles) : null;
  const card = id == null ? null : await fetchCounterpartyCard(id, roles);

  return (
    <Card className="px-[18px] py-[14px]">
      <CardHeader>
        <span aria-hidden>🪪</span>
        <span>Клиент · 360°</span>
      </CardHeader>
      <CardBody className="space-y-2.5">{card ? <Body card={card} /> : <Empty />}</CardBody>
    </Card>
  );
}

function Empty() {
  return (
    <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
      <span className="font-semibold text-faint">нет в MDM · </span>
      контрагент не найден в справочнике (контрагентов 1С загружает отдельная сессия) — досье
      появится после загрузки.
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
