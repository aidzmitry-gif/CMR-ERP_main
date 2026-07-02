import { AppShell } from "@/components/app-shell";
import { DayScoreboard } from "@/components/rop/day-scoreboard";
import { RopTabs } from "@/components/rop/rop-tabs";

/** Скорборд план/факт показателей дня (менеджер/РОП), реальный бэк /sales/kpis. */
export default function RopScoreboardPage() {
  return (
    <AppShell crumbs={["CRM", "РОП · Скорборд"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          <div>
            <h1 className="text-xl font-bold text-ink">Скорборд дня — план / факт</h1>
            <p className="mt-1 text-sm text-muted">
              Показатели менеджера и отдела за период · валюта — бел. руб. (BYN) · данные с бэка.
            </p>
          </div>
          <RopTabs active="scoreboard" />
          <DayScoreboard />
        </div>
      </main>
    </AppShell>
  );
}
