import { AppShell } from "@/components/app-shell";
import { ShipmentStatus } from "@/components/shipments/shipment-status";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Статус отгрузки"]}>
      <ShipmentStatus />
    </AppShell>
  );
}
