import { AppShell } from "@/components/app-shell";
import { AccountingStockIssues } from "@/components/erp/accounting-stock-issues";
export default function StockIssuesPage() {
  return <AppShell crumbs={["ERP", "Бухгалтерия", "Списание по накладной"]}><AccountingStockIssues /></AppShell>;
}
