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
import { confirmProgrammaticDocumentNavigation } from "@/lib/use-unsaved-document-guard";

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

/** Keeps the shell stable while mounting call UI only for an eligible CRM matrix role. */
export function ActiveCallProvider({ children, enabled = false }: {
  children: React.ReactNode;
  enabled?: boolean;
}) {
  return (
    <>
      {children}
      {enabled ? <ActiveCallSubscriptionOverlay /> : null}
    </>
  );
}

function ActiveCallSubscriptionOverlay() {
  const [card, setCard] = useState<CallCard | null>(null);
  // cockpit = открыт рабочий кокпит разговора (после «Принять»), отдельно от screen-pop.
  const [cockpit, setCockpit] = useState<CallContext | null>(null);
  const router = useRouter();

  // Cleanup + флаг подавляют события, уже попавшие в очередь при отписке.
  useEffect(() => {
    let subscribed = true;
    const unsubscribe = subscribeCalls((nextCard) => {
      if (subscribed) setCard(nextCard);
    });
    return () => {
      subscribed = false;
      unsubscribe();
    };
  }, []);

  return (
    <>
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
            if (card.deal_id && !confirmProgrammaticDocumentNavigation()) return;
            if (card.deal_id) router.push(`/crm/deals/${card.deal_id}`);
            setCard(null);
          }}
          onCreateDeal={async () => {
            await callLinkDeal(card.id, { create: true });
            setCard(null);
            router.refresh();
          }}
          onCreateLead={async () => {
            if (!confirmProgrammaticDocumentNavigation()) return;
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
