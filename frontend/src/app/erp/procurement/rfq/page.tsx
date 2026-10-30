import { AppShell } from "@/components/app-shell";
import { ProcurementRfqView } from "@/components/erp/procurement-rfq-view";

export default function ProcurementRfqPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки", "Тендер / RFQ"]}>
      <div className="flex min-w-0 flex-1 flex-col">

        <ProcurementRfqView />
      </div>
    </AppShell>
  );
}
