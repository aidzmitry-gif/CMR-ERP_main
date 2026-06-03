import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function MarketingPage() {
  return (
    <AppShell crumbs={["ERP", "Маркетинг"]}>
      <ModuleBoard
        title="Маркетинг"
        subtitle="Кампании и привлечённые лиды"
        endpoint="/marketing/campaigns"
        columns={[
          { key: "name", label: "Кампания" },
          { key: "channel", label: "Канал" },
          { key: "budget", label: "Бюджет" },
          { key: "leads", label: "Лиды" },
        ]}
        fields={[
          { key: "name", label: "Кампания" },
          { key: "channel", label: "Канал" },
          { key: "budget", label: "Бюджет", type: "number", default: 0 },
          { key: "leads", label: "Лиды", type: "number", default: 0 },
        ]}
      />
    </AppShell>
  );
}
