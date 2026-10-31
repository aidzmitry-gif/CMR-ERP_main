import { AppShell } from "@/components/app-shell";
import { RopOverview } from "@/components/rop/rop-overview";

export default function RopOverviewPage() {
  return (
    <AppShell crumbs={["CRM", "РОП · Обзор"]}>
      <main className="min-w-0 flex-1 overflow-auto bg-canvas p-4 sm:p-6">
        <RopOverview />
      </main>
    </AppShell>
  );
}
