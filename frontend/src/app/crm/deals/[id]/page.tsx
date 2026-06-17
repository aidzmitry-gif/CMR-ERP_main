import Link from "next/link";
import { ArrowLeft, Calendar, Flag, User } from "lucide-react";
import { ChannelButtons } from "@/components/channels";
import { DealActions } from "@/components/deal-actions";
import { DealAiAssistant } from "@/components/deal-ai-assistant";
import { DealApprovals } from "@/components/deal-approvals";
import { DealContacts } from "@/components/deal-contacts";
import { DealEditButton } from "@/components/deal-edit-button";
import { DealDocuments } from "@/components/deal-documents";
import { DealItems } from "@/components/deal-items";
import { DealTasks } from "@/components/deal-tasks";
import { DealMessages } from "@/components/deal-messages";
import { PriorityBadge } from "@/components/priority-badge";
import { fetchDealDetail } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { currentRole } from "@/lib/role-server";

export default async function DealDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = await fetchDealDetail(id, await currentRole());

  return (
    <div className="mx-auto max-w-md px-4 py-6">
      <Link
        href="/crm/deals"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"
      >
        <ArrowLeft size={16} /> К сделкам
      </Link>

      <div className="rounded-2xl bg-surface p-5 shadow-card">
        {/* Шапка */}
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted">№ {d.number}</span>
          <div className="flex items-center gap-2">
            <PriorityBadge priority={d.priority} withIcon />
            <DealEditButton
              dealId={id}
              title={d.description}
              amount={d.amount}
              nextStep={d.nextStep}
              dealDate={d.dealDate}
            />
          </div>
        </div>

        <h1 className="mt-3 text-2xl font-bold text-ink">{d.company}</h1>
        <p className="text-muted">{d.description}</p>
        <div className="mt-3 text-2xl font-bold text-ink">{formatMoney(d.amount)}</div>

        {/* След. шаг */}
        <div className="mt-3 flex items-center gap-2 text-sm">
          <Flag size={16} className="text-accent-ink" />
          <span className="text-muted">След. шаг:</span>
          <span className="font-medium text-ink">{d.nextStep}</span>
        </div>

        {/* Контакт + дата */}
        <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-4">
          <span className="inline-flex items-center gap-2 text-sm text-ink">
            <User size={16} className="text-faint" /> {d.contact}
          </span>
          <span className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm text-ink">
            <Calendar size={15} className="text-accent-ink" /> {d.datetime}
          </span>
        </div>

        {/* Контакты контрагента */}
        <DealContacts dealId={id} />

        {/* Номенклатура (редактирование позиций) */}
        <DealItems dealId={id} />

        {/* Задачи по сделке (SALES-41) */}
        <DealTasks dealId={id} />

        {/* AI-ассистент сделки (резюме / следующий шаг) */}
        <DealAiAssistant dealId={id} />

        {/* Сообщения (омниканальная переписка, из API) */}
        <DealMessages dealId={id} />

        {/* Документы сделки (счёт/договор/заказ) + запись в 1С */}
        <DealDocuments dealId={id} />

        {/* Согласования (human-in-the-loop) */}
        <DealApprovals dealId={id} />

        {/* Фокус / Приоритет / Избранное (интерактив через PATCH) */}
        <DealActions dealId={id} focus={d.focus} starred={d.starred} priority={d.priority} />

        {/* Каналы */}
        <div className="mt-5">
          <ChannelButtons dealId={id} />
        </div>
      </div>
    </div>
  );
}
