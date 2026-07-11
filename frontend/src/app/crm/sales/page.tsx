import { AppShell } from "@/components/app-shell";
import { SalesJournal } from "@/components/sales/sales-journal";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Журнал продаж"]}>
      <SalesJournal />
    </AppShell>
  );
}
