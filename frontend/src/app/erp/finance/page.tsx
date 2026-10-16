import { AppShell } from "@/components/app-shell";
import { FinanceView } from "@/components/erp/finance-view";

export default async function FinancePage({
  searchParams,
}: {
  searchParams?: Promise<{ tab?: string | string[] }>;
}) {
  const params = searchParams ? await searchParams : {};
  const initialTab = typeof params.tab === "string" ? params.tab : undefined;
  return (
    <AppShell crumbs={["ERP", "Финансы"]}>
      <FinanceView initialTab={initialTab} />
    </AppShell>
  );
}
