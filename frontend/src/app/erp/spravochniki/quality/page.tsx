import { AppShell } from "@/components/app-shell";
import { SpravQuality } from "@/components/erp/spravochniki/sprav-quality";
import { fetchQualitySummary } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravQualityPage() {
  const role = await currentRole();
  const summary = await fetchQualitySummary(role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Качество данных"]}>
      <div className="mx-auto w-full max-w-[1280px] p-6">
        <SpravQuality summary={summary} />
      </div>
    </AppShell>
  );
}
