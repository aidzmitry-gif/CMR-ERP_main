import { AppShell } from "@/components/app-shell";
import { WmsMovements } from "@/components/erp/wms-movements";
import { currentRole } from "@/lib/role-server";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchLocationsServer, fetchMovementsServer } from "@/lib/wms-ops";

export default async function WmsMovementsPage() {
  const role = await currentRole();
  const auth = await backendAuthHeaders(role);
  const companyResponse = await fetch(`${process.env.BACKEND_URL ?? "http://127.0.0.1:8000"}/wms/receipt-organizations`, { cache: "no-store", headers: auth });
  if (!companyResponse.ok) throw new Error("Не удалось загрузить доступные юрлица");
  const organizations: { id: number; name: string }[] = await companyResponse.json();
  const [movements, locations] = await Promise.all([
    fetchMovementsServer(role, auth),
    fetchLocationsServer(role, auth),
  ]);

  return (
    <AppShell crumbs={["ERP", "Склад", "Движения и операции"]}>
      <WmsMovements initial={movements} locations={locations} organizations={organizations} />
    </AppShell>
  );
}
