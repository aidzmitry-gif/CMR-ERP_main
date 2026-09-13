import { AppShell } from "@/components/app-shell";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { ProcurementOwnership } from "@/components/erp/procurement-ownership";
export default function Page() {
  return <AppShell crumbs={["ERP", "Закупки", "Юрлица и связи"]}><div className="flex min-w-0 flex-1 flex-col"><ProcurementNav /><div className="flex min-h-0 flex-1"><ProcurementOwnership /></div></div></AppShell>;
}
