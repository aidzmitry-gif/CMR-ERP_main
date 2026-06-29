import { AppShell } from "@/components/app-shell";
import { RopPlanFact } from "@/components/crm/rop-plan-fact";
import { RopTabs } from "@/components/rop/rop-tabs";

export default function RopPlanFactPage() {
  const now = new Date();
  const defaultPeriod = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

  return (
    <AppShell crumbs={["CRM", "РОП", "План/Факт"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          <div>
            <h1 className="text-xl font-bold text-ink">План/Факт — менеджеры отдела продаж</h1>
            <p className="mt-1 text-sm text-muted">
              Выполнение плана по сделкам и выручке за выбранный месяц · валюта BYN.
            </p>
          </div>

          <RopTabs active="plan-fact" />

          <RopPlanFact defaultPeriod={defaultPeriod} />
        </div>
      </main>
    </AppShell>
  );
}
