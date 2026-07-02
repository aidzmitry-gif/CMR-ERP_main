import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function WmsOperationsPage() {
  return (
    <AppShell crumbs={["ERP", "Склад", "Воронка операций"]}>
      <FunnelBoard
        title="Воронка операций"
        subtitle="Поступление → приёмка → контроль → размещение → отгрузка."
        boardPath="/wms/board"
        createPath="/wms/ops"
        patchPath="/wms/ops"
        fields={[
          { key: "counterparty", label: "Контрагент" },
          { key: "title", label: "Описание" },
          { key: "items_count", label: "Позиций", type: "number", default: 0 },
          { key: "amount", label: "Сумма, ₽", type: "number", default: 0 },
        ]}
        showActions
        {...FUNNEL_EXTRAS.wms}
      />
    </AppShell>
  );
}
