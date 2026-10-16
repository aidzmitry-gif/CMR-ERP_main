import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import Link from "next/link";

export default function ProductionPage() {
  return (
    <AppShell crumbs={["ERP", "Производство"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <nav aria-label="Документы производства" className="flex flex-wrap gap-3 border-b border-line p-4 text-sm">
          <Link href="/erp/production/bom" className="text-accent hover:underline">Спецификации сборок</Link>
          <Link href="/erp/production/vyrabotka" className="text-accent hover:underline">Выработка сборщиков</Link>
          <Link href="/erp/production/otk" className="text-accent hover:underline">Контроль качества</Link>
        </nav>
        <div className="flex min-h-0 flex-1">
      <FunnelBoard
        title="Производство"
        subtitle="Заказы из ERP: от очереди до готовности. Спецификации, выработка и контроль качества доступны в документах производства."
        boardPath="/production/board"
        createPath="/production/orders"
        patchPath="/production/orders"
        showSum={false}
        fields={[
          { key: "product", label: "Изделие" },
          { key: "qty", label: "Кол-во", type: "number", default: 1 },
        ]}
        createLabel="Создать наряд"
        statusNote="Показаны заказы ERP. Обеспеченность и риск по заказу появятся после подключения его спецификации и фактических остатков."
      />
        </div>
      </div>
    </AppShell>
  );
}
