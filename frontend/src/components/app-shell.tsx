import { redirect } from "next/navigation";

import { ActiveCallProvider } from "@/components/calls/active-call-provider";
import { CurrencyProvider } from "@/components/kanban/currency-context";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { fetchAccess } from "@/lib/access";
import { currentRole, currentUserName } from "@/lib/role-server";

export async function AppShell({
  crumbs,
  children,
}: {
  crumbs: string[];
  children: React.ReactNode;
}) {
  // гейт: без dev-логина уводим на /login
  const userName = await currentUserName();
  if (!userName) redirect("/login");

  // текущая роль из cookie; матрицу доступных модулей берём с backend
  const role = await currentRole();
  const access = await fetchAccess(role);
  // backend недоступен → не прячем ничего (allowedSlugs=null), чтобы UI не «ослеп»
  const allowedSlugs = access ? access.matrix[role] ?? [] : null;
  const roleTitle = access?.roles.find((r) => r.slug === role)?.title ?? role;

  return (
    // CurrencyProvider — единый на всю оболочку: переключатель ЮЛ (валюта) влияет на ВСЕ
    // деньги (карточка/drawer/окно звонка), а окно звонка живёт внутри ActiveCallProvider,
    // поэтому провайдер обязан быть выше него (иначе входящий звонок вне /crm дал бы ₽).
    <CurrencyProvider>
      {/* Подписка на входящие звонки (SSE) + всплывающее окно — на любом экране оболочки.
          owner = ФИО продавца (cookie aios_user), по нему backend пушит карточки (SALES-50). */}
      <ActiveCallProvider owner={userName ?? undefined}>
        <div className="flex h-screen overflow-hidden">
          <Sidebar allowedSlugs={allowedSlugs} userName={userName} roleTitle={roleTitle} />
          <div className="flex flex-1 flex-col overflow-hidden">
            <Topbar crumbs={crumbs} />
            <div className="flex flex-1 overflow-hidden">{children}</div>
          </div>
        </div>
      </ActiveCallProvider>
    </CurrencyProvider>
  );
}
