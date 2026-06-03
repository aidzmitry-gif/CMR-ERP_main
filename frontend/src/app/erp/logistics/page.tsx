import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function LogisticsPage() {
  return (
    <AppShell crumbs={["ERP", "Логистика"]}>
      <ModuleBoard
        title="Логистика"
        subtitle="Отгрузки и доставки"
        endpoint="/logistics/shipments"
        columns={[
          { key: "customer", label: "Получатель" },
          { key: "address", label: "Адрес" },
          { key: "carrier", label: "Перевозчик" },
          { key: "status", label: "Статус" },
        ]}
        fields={[
          { key: "customer", label: "Получатель" },
          { key: "address", label: "Адрес" },
          { key: "carrier", label: "Перевозчик" },
        ]}
      />
    </AppShell>
  );
}
