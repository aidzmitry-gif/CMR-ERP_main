import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";

export default function ServicePage() {
  return (
    <AppShell crumbs={["ERP", "Сервис и поддержка"]}>
      <ModuleBoard
        title="Сервис и поддержка"
        subtitle="Обращения клиентов"
        endpoint="/service/tickets"
        columns={[
          { key: "customer", label: "Клиент" },
          { key: "subject", label: "Тема" },
          { key: "status", label: "Статус" },
        ]}
        fields={[
          { key: "customer", label: "Клиент" },
          { key: "subject", label: "Тема" },
        ]}
      />
    </AppShell>
  );
}
