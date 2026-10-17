import { AppShell } from "@/components/app-shell";
import { SpravSkuCard } from "@/components/erp/spravochniki/sprav-sku-card";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchSkuCard } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SkuCardPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const card = await fetchSkuCard(decodeURIComponent(code), role, authHeaders);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Номенклатура"]}>
      {card ? (
        <SpravSkuCard card={card} />
      ) : (
        <div className="flex flex-1 items-center justify-center text-muted">
          Номенклатура не найдена
        </div>
      )}
    </AppShell>
  );
}
