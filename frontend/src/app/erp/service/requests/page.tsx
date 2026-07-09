import { AppShell } from "@/components/app-shell";
import { ServiceRequestsClient } from "./service-requests-client";

export default function ServiceRequestsPage() {
  return (
    <AppShell crumbs={["ERP", "Сервис и поддержка", "Заявки"]}>
      <ServiceRequestsClient />
    </AppShell>
  );
}
