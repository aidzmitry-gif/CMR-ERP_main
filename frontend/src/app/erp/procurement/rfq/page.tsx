import { AppShell } from "@/components/app-shell";
import { ProcurementRfqView } from "@/components/erp/procurement-rfq-view";
import { ProcurementNav } from "@/components/erp/procurement-nav";

export default function ProcurementRfqPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки", "Тендер / RFQ"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <ProcurementNav />
        <ProcurementRfqView />
      </div>
    </AppShell>
  );
}
