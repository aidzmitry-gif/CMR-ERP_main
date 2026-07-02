import { AppShell } from "@/components/app-shell";
import { MarketingCampaignBoard } from "@/components/erp/marketing-campaign-board";
import { ModuleBoard } from "@/components/erp/module-board";

export default function MarketingPage() {
  return (
    <AppShell crumbs={["ERP", "Маркетинг"]}>
      <ModuleBoard
        title="Маркетинг"
        subtitle="Кампании и лиды. «Запустить» — лиды попадают в воронку CRM как сделки."
        endpoint="/marketing/campaigns"
        columns={[
          { key: "name", label: "Кампания" },
          { key: "channel", label: "Канал" },
          { key: "utm_source", label: "UTM source" },
          { key: "utm_medium", label: "UTM medium" },
          { key: "utm_campaign", label: "UTM campaign" },
          { key: "budget", label: "Бюджет BYN" },
          { key: "leads", label: "Лиды" },
          { key: "goal", label: "Цель" },
        ]}
        fields={[
          { key: "name", label: "Кампания" },
          { key: "channel", label: "Канал" },
          { key: "budget", label: "Бюджет BYN", type: "number", default: 0 },
          { key: "leads", label: "Лиды", type: "number", default: 0 },
          { key: "utm_source", label: "UTM source" },
          { key: "utm_medium", label: "UTM medium" },
          { key: "utm_campaign", label: "UTM campaign" },
          { key: "goal", label: "Цель" },
        ]}
        action={{ label: "Запустить", path: "/marketing/campaigns/{id}/launch" }}
      />
      <MarketingCampaignBoard />
    </AppShell>
  );
}
