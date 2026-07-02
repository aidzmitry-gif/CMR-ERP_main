import { AppShell } from "@/components/app-shell";
import { SpravAdmin } from "@/components/erp/spravochniki/sprav-admin";
import { fetchPendingReferenceApprovals } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravAdminPage() {
  const role = await currentRole();
  const pending = await fetchPendingReferenceApprovals(role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Модерация"]}>
      <div className="mx-auto w-full max-w-[1100px] p-6">
        <SpravAdmin initial={pending} />
      </div>
    </AppShell>
  );
}
