import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function ProcurementPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки"]}>
      <ModuleBoard
        title="Закупки"
        subtitle="Заявки на закупку у поставщиков"
        endpoint="/procurement/requests"
        columns={[
          { key: "supplier", label: "Поставщик" },
          { key: "item", label: "Позиция" },
          { key: "qty", label: "Кол-во" },
          { key: "status", label: "Статус" },
        ]}
        fields={[
          { key: "supplier", label: "Поставщик" },
          { key: "item", label: "Позиция" },
          { key: "qty", label: "Кол-во", type: "number", default: 1 },
        ]}
      />
    </AppShell>
  );
}
