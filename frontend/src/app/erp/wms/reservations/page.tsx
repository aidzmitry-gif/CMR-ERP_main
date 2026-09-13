import { AppShell } from "@/components/app-shell";
import { WmsReservations } from "@/components/erp/wms-reservations";

export default function ReservationsPage() {
  return <AppShell crumbs={["ERP", "Склад", "Резервы"]}><WmsReservations /></AppShell>;
}
