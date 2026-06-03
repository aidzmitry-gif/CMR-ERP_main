import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function WmsPage() {
  return (
    <AppShell crumbs={["ERP", "Склад"]}>
      <ModuleBoard
        title="Склад"
        subtitle="Движения по складу (приход/расход)"
        endpoint="/wms/movements"
        columns={[
          { key: "sku_code", label: "SKU" },
          { key: "warehouse", label: "Склад" },
          { key: "kind", label: "Тип" },
          { key: "qty", label: "Кол-во" },
        ]}
        fields={[
          { key: "sku_code", label: "SKU" },
          { key: "warehouse", label: "Склад", default: "Главный" },
          { key: "kind", label: "Тип (in/out)", default: "in" },
          { key: "qty", label: "Кол-во", type: "number", default: 1 },
        ]}
      />
    </AppShell>
  );
}
