import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function FinancePage() {
  return (
    <AppShell crumbs={["ERP", "Финансы"]}>
      <ModuleBoard
        title="Финансы"
        subtitle="Платежи по сделкам и документам"
        endpoint="/finance/payments"
        columns={[
          { key: "ref", label: "Назначение" },
          { key: "amount", label: "Сумма" },
          { key: "status", label: "Статус" },
        ]}
        fields={[
          { key: "ref", label: "Назначение" },
          { key: "amount", label: "Сумма", type: "number", default: 0 },
        ]}
      />
    </AppShell>
  );
}
