import { AppShell } from "@/components/app-shell";
import { SpravSkuCard } from "@/components/erp/spravochniki/sprav-sku-card";
import { fetchSkuCard } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SkuCardPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  const role = await currentRole();
  const card = await fetchSkuCard(decodeURIComponent(code), role);

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
