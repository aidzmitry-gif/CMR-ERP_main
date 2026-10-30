import { AppShell } from "@/components/app-shell";
import { WorktimeView } from "@/components/erp/worktime-view";

export default async function WorktimePage({ searchParams }: {
  searchParams: Promise<{ tab?: string; period?: string }>;
}) {
  const params = await searchParams;
  return (
    <AppShell crumbs={["ERP", "HR", "Учёт времени"]}>
      <WorktimeView initialTab={params.tab === "sheet" ? "sheet" : "day"}
        initialPeriod={params.period && /^\d{4}-\d{2}$/.test(params.period) ? params.period : undefined} />
    </AppShell>
  );
}
