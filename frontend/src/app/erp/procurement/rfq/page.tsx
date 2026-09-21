import { AppShell } from "@/components/app-shell";
import { ProcurementRfqView } from "@/components/erp/procurement-rfq-view";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { fetchRfqsServer } from "@/lib/procurement-rfq";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementRfqPage() {
  const role = await currentRole();
  const rfqs = await fetchRfqsServer(role);

  return (
    <AppShell crumbs={["ERP", "Закупки", "Тендер / RFQ"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <ProcurementNav />
        <ProcurementRfqView initial={rfqs} />
      </div>
    </AppShell>
  );
}
