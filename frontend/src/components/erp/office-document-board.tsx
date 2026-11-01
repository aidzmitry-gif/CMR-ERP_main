"use client";

import { OfficeView } from "@/components/erp/office-view";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import type { FunnelKpi, FunnelStage } from "@/lib/types";

function documentCounts(stages: FunnelStage[]): FunnelKpi[] {
  const count = (id: string) => stages.find(stage => stage.id === id)?.count ?? 0;
  return [
    { label: "Доступных документов", value: String(stages.reduce((total, stage) => total + stage.count, 0)), note: "Снимок текущего доступа", tone: "blue" },
    { label: "Черновики", value: String(count("draft")), note: "Проверка и назначение", tone: "violet" },
    { label: "К подготовке", value: String(count("ready")), note: "Условия и точный счёт", tone: "cyan" },
    { label: "Сбор документов", value: String(count("docs")), note: "Комплект по документу", tone: "amber" },
    { label: "Ожидание оплаты", value: String(count("await_pay")), note: "Этап документа, не факт долга", tone: "green" },
  ];
}

export function OfficeDocumentBoard() {
  return <OfficeView board={<FunnelBoard
    title="Офис-менеджер"
    subtitle="Черновики, подготовка, выдача и оформление документов по сделкам."
    boardPath="/office/board"
    createPath="/office/docs"
    patchPath="/office/docs"
    currency="BYN"
    createLabel="Создать документ"
    fields={[
      { key: "company", label: "Компания" },
      { key: "title", label: "Описание" },
      { key: "amount", label: "Сумма, BYN", type: "number", default: 0 },
    ]}
    kpis={documentCounts}
    summary={[]}
    statusNote="Снимок документов в вашем доступе, без отбора по датам. Суммы документов — в BYN; оплату проверяйте по платежам."
  />} />;
}
