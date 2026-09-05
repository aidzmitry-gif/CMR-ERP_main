import { redirect } from "next/navigation";

import { ActiveCallProvider } from "@/components/calls/active-call-provider";
import { ChatsPanel } from "@/components/chats-panel";
import { CurrencyProvider } from "@/components/kanban/currency-context";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { fetchAccess } from "@/lib/access";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { frontendAuthMode } from "@/lib/auth-mode";
import { resolveAppRole } from "@/lib/app-role";
import { currentRole, currentUserName } from "@/lib/role-server";

export async function AppShell({
  crumbs,
  headerActions,
  children,
}: {
  crumbs: string[];
  /** Доп. контент правее хлебных крошек в шапке (напр. переключатель ЮЛ, «Стадии»). */
  headerActions?: React.ReactNode;
  children: React.ReactNode;
}) {
  // гейт: без сессии (dev-cookie или OIDC callback) уводим на /login
  const userName = await currentUserName();
  if (!userName) redirect("/login");

  // текущая роль из cookie; матрицу доступных модулей берём с backend
  const cookieRole = await currentRole();
  const access = await fetchAccess(cookieRole, await backendAuthHeaders(cookieRole));
  const oidc = frontendAuthMode() === "oidc";
  if (oidc && access?.current_roles.includes("Гость")) redirect("/login?error=session_expired");
  // The backend verifies the token. A stale display cookie must not advertise
  // director navigation after the authenticated role changed.
  const role = oidc && access ? resolveAppRole(access.current_roles) : cookieRole;
  const allowedSlugs = access ? access.matrix[role] ?? [] : oidc ? [] : null;
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
            <Topbar crumbs={crumbs} headerActions={headerActions} />
            {/* Вертикальный скролл на уровне оболочки: страницы без своего overflow-контейнера
                (справочники и т.п.) прокручиваются здесь; страницы со своим <main overflow-auto>
                (доска сделок) скроллят сами — вложенный скролл корректен. min-h-0 нужен, чтобы
                flex-потомок реально получил скролл, а не растягивал родителя (типовой flexbox-гоча). */}
            <div className="flex min-h-0 flex-1 overflow-y-auto">{children}</div>
          </div>
          <ChatsPanel />
        </div>
      </ActiveCallProvider>
    </CurrencyProvider>
  );
}
