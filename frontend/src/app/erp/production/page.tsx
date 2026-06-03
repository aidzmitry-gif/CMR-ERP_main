import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function ProductionPage() {
  return (
    <AppShell crumbs={["ERP", "Производство"]}>
      <ModuleBoard
        title="Производство"
        subtitle="Производственные заказы"
        endpoint="/production/orders"
        columns={[
          { key: "product", label: "Продукт" },
          { key: "qty", label: "Кол-во" },
          { key: "status", label: "Статус" },
        ]}
        fields={[
          { key: "product", label: "Продукт" },
          { key: "qty", label: "Кол-во", type: "number", default: 1 },
        ]}
      />
    </AppShell>
  );
}
