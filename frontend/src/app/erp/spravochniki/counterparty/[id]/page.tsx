import { AppShell } from "@/components/app-shell";
import { SpravCard } from "@/components/erp/spravochniki/sprav-card";
import { fetchCounterpartyCard } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function CounterpartyCardPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const role = await currentRole();
  const card = await fetchCounterpartyCard(Number(id), role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Контрагент"]}>
      {card ? (
        <SpravCard card={card} />
      ) : (
        <div className="flex flex-1 items-center justify-center text-muted">
          Контрагент не найден
        </div>
      )}
    </AppShell>
  );
}
