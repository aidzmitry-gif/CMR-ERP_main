import { AppShell } from "@/components/app-shell";
import { VyrabotkaTable } from "@/components/erp/vyrabotka-table";
import { fetchPayrollServer } from "@/lib/production-vyrabotka";
import { currentRole } from "@/lib/role-server";

export default async function ProductionVyrabotkaPage() {
  const role = await currentRole();
  const payroll = await fetchPayrollServer(role);

  return (
    <AppShell crumbs={["ERP", "Производство", "Выработка и оценка"]}>
      <VyrabotkaTable initial={payroll} />
    </AppShell>
  );
}
