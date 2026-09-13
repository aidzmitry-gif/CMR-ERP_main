import { AppShell } from "@/components/app-shell";
import { SalesJournal } from "@/components/sales/sales-journal";
import Link from "next/link";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Журнал продаж"]} headerActions={
      <Link href="/crm/mail" className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-accent-ink hover:bg-accent-soft">
        Почта отдела продаж
      </Link>
    }>
      <SalesJournal />
    </AppShell>
  );
}
