import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function HrPage() {
  return (
    <AppShell crumbs={["ERP", "HR"]}>
      <ModuleBoard
        title="HR"
        subtitle="Сотрудники"
        endpoint="/hr/employees"
        columns={[
          { key: "full_name", label: "ФИО" },
          { key: "position", label: "Должность" },
          { key: "department", label: "Отдел" },
          { key: "status", label: "Статус" },
        ]}
        fields={[
          { key: "full_name", label: "ФИО" },
          { key: "position", label: "Должность" },
          { key: "department", label: "Отдел" },
        ]}
      />
    </AppShell>
  );
}
