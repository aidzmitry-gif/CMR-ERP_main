import { AppShell } from "@/components/app-shell";
import { ProcurementCompanyDocuments } from "@/components/erp/procurement-company-documents";
export default function CompanyDocumentsPage() {
  return <AppShell crumbs={["ERP", "Закупки", "Документы юрлица"]}><div className="flex min-w-0 flex-1 flex-col"><ProcurementCompanyDocuments /></div></AppShell>;
}
