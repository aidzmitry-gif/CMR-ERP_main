import { AppShell } from "@/components/app-shell";
import { HrPayrollView } from "@/components/erp/hr-payroll-view";

export default function HrPayrollPage() {
  return (
    <AppShell crumbs={["ERP", "HR · Подбор", "Начисления"]}>
      <HrPayrollView />
    </AppShell>
  );
}
