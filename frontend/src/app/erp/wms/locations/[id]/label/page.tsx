import { AppShell } from "@/components/app-shell";
import { WmsLocationLabel } from "@/components/erp/wms-location-label";

export default async function WmsLocationLabelPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <AppShell crumbs={["ERP", "Склад", "Размещение", "Этикетка"]}>
      <WmsLocationLabel id={Number(id)} />
    </AppShell>
  );
}
