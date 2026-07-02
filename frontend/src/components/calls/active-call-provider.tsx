"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CallWindow, type CallContext } from "@/components/calls/call-window";
import { IncomingCallCard } from "@/components/calls/incoming-call-card";
import {
  callComment,
  callLinkDeal,
  callResult,
  createLead,
  subscribeCalls,
  type CallCard,
} from "@/lib/api";

/** Контекст кокпита разговора из карточки входящего: есть сделка → deal, иначе новый клиент. */
function contextFromCard(card: CallCard): CallContext {
  if (card.deal_id) {
    return {
      kind: "deal",
      dealId: String(card.deal_id),
      number: String(card.deal_id),
      company: card.phone ?? "Клиент",
      phone: card.phone ?? undefined,
    };
  }
  return {
    kind: "new",
    company: card.phone ?? "Новый клиент",
    phone: card.phone ?? undefined,
    callId: card.id,
  };
}

/**
 * Глобальная подписка продавца на поток входящих звонков (SSE) + всплывающее окно.
 * Монтируется в оболочке (AppShell) — окно доступно на любом экране CRM/ERP.
 * ``owner`` — ФИО продавца (= Deal.owner), по которому backend пушит карточки.
 */
export function ActiveCallProvider({
  owner,
  children,
}: {
  owner?: string;
  children: React.ReactNode;
}) {
  const [card, setCard] = useState<CallCard | null>(null);
  // cockpit = открыт рабочий кокпит разговора (после «Принять»), отдельно от screen-pop.
  const [cockpit, setCockpit] = useState<CallContext | null>(null);
  const router = useRouter();

  // subscribeCalls возвращает функцию отписки → она же cleanup эффекта.
  useEffect(() => subscribeCalls(owner, setCard), [owner]);

  return (
    <>
      {children}
      {card && (
        <IncomingCallCard
          card={card}
          onClose={() => setCard(null)}
          onAccept={() => {
            // Принять звонок → раскрыть рабочий кокпит (скрипт + подбор товара + счёт).
            setCockpit(contextFromCard(card));
            setCard(null);
          }}
          onComment={(t) => void callComment(card.id, t)}
          onResult={(r) => {
            void callResult(card.id, r);
            setCard(null);
          }}
          onLinkDeal={() => {
            if (card.deal_id) router.push(`/crm/deals/${card.deal_id}`);
            setCard(null);
          }}
          onCreateDeal={async () => {
            await callLinkDeal(card.id, { create: true });
            setCard(null);
            router.refresh();
          }}
          onCreateLead={async () => {
            await createLead({
              source: "phone",
              phone: card.phone ?? "",
              message: `Звонок ${card.phone ?? card.call_id}`,
            });
            router.push("/crm/leads");
            setCard(null);
          }}
        />
      )}

      {/* Рабочий кокпит разговора — открывается после «Принять» входящего (и тот же
          компонент, что и для исходящих из сделки/лида). */}
      <CallWindow context={cockpit} onClose={() => setCockpit(null)} />
    </>
  );
}
