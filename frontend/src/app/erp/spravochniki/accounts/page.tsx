import { AppShell } from "@/components/app-shell";
import { AccountingChart } from "@/components/erp/accounting-chart";

export default function AccountsPage() {
  return <AppShell crumbs={["ERP", "Справочники", "План счетов"]}><AccountingChart /></AppShell>;
}
