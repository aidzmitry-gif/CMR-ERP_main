import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function ProductionPage() {
  return (
    <AppShell crumbs={["ERP", "Производство"]}>
      <ModuleBoard
        title="Производство"
        subtitle="Производственные заказы. Готовность («done») создаёт приход на склад."
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
        statusKey="status"
        statusFlow={["planned", "in_progress", "done"]}
        patchPath="/production/orders"
      />
    </AppShell>
  );
}
