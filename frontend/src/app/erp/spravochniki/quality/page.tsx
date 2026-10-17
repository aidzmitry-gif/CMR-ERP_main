import { AppShell } from "@/components/app-shell";
import { SpravQuality } from "@/components/erp/spravochniki/sprav-quality";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchQualitySummary } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravQualityPage() {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const summary = await fetchQualitySummary(role, authHeaders);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Качество данных"]}>
      <div className="mx-auto w-full max-w-[1280px] p-6">
        <SpravQuality summary={summary} />
      </div>
    </AppShell>
  );
}
