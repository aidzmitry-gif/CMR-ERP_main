import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function ProcurementPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки"]}>
      <FunnelBoard
        title="Закупки"
        subtitle="Воронка закупок: от потребности до завершения. «Приёмка / QC» создаёт приход на склад."
        boardPath="/procurement/board"
        createPath="/procurement/requests"
        patchPath="/procurement/requests"
        fields={[
          { key: "supplier", label: "Поставщик" },
          { key: "item", label: "Позиция" },
          { key: "qty", label: "Кол-во", type: "number", default: 1 },
          { key: "amount", label: "Сумма, ₽", type: "number", default: 0 },
        ]}
        showChannels
        {...FUNNEL_EXTRAS.procurement}
      />
    </AppShell>
  );
}
