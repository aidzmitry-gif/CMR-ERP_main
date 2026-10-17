import { AppShell } from "@/components/app-shell";
import { SpravRates } from "@/components/erp/spravochniki/sprav-rates";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchCurrencyRates, fetchVatRates } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravRatesPage() {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const [currencyRates, vatRates] = await Promise.all([
    fetchCurrencyRates(undefined, role, authHeaders),
    fetchVatRates(undefined, role, authHeaders),
  ]);
  return (
    <AppShell crumbs={["ERP", "Справочники", "Курсы и ставки"]}>
      <SpravRates initialCurrencyRates={currencyRates} initialVatRates={vatRates} />
    </AppShell>
  );
}
