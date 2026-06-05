import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function WmsPage() {
  return (
    <AppShell crumbs={["ERP", "Склад"]}>
      <FunnelBoard
        title="Склад"
        subtitle="Воронка операций: поступление → приёмка → контроль → размещение → отгрузка."
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
