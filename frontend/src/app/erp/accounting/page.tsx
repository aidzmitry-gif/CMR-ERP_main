import { AppShell } from "@/components/app-shell";
import { AccountingView } from "@/components/erp/accounting-view";

export default function AccountingPage() {
  return <AppShell crumbs={["ERP", "Бухгалтерия"]}><AccountingView /></AppShell>;
}
