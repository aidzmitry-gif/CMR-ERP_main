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

const CALL_STREAM_DENIED_ROLES = new Set(["admin", "director", "commercial", "Гость"]);

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
  const rawCurrentRoles: unknown = access?.current_roles;
  const currentRoles = Array.isArray(rawCurrentRoles)
    && rawCurrentRoles.length > 0
    && rawCurrentRoles.every((currentRole: unknown) => typeof currentRole === "string")
    ? rawCurrentRoles as string[]
    : null;
  if (oidc && currentRoles?.includes("Гость")) redirect("/login?error=session_expired");
  // The backend verifies the token. A stale display cookie must not advertise
  // director navigation after the authenticated role changed.
  const role = oidc && access && currentRoles ? resolveAppRole(currentRoles) : cookieRole;
  const rawMatrix: unknown = access?.matrix;
  const roleMatrix = rawMatrix !== null && typeof rawMatrix === "object" && !Array.isArray(rawMatrix)
    ? rawMatrix as Record<string, unknown>
    : null;
  const rawModules = roleMatrix?.[role];
  const allowedSlugs = Array.isArray(rawModules)
    ? rawModules.filter((slug): slug is string => typeof slug === "string")
    : access ? [] : oidc ? [] : null;
  const roleMetadata = Array.isArray(access?.roles)
    ? access.roles.find((entry) => entry && entry.slug === role)
    : undefined;
  const roleTitle = roleMetadata?.title ?? role;
  const canSubscribeToCalls = Boolean(
    currentRoles
    && !currentRoles.some((currentRole) => CALL_STREAM_DENIED_ROLES.has(currentRole))
    && currentRoles.some((currentRole) => {
      const modules = roleMatrix?.[currentRole];
      return Array.isArray(modules) && modules.includes("crm");
    }),
  );

  return (
    // CurrencyProvider — единый на всю оболочку: переключатель ЮЛ (валюта) влияет на ВСЕ
    // деньги (карточка/drawer/окно звонка), а окно звонка живёт внутри ActiveCallProvider,
    // поэтому провайдер обязан быть выше него (иначе входящий звонок вне /crm дал бы ₽).
    <CurrencyProvider>
      {/* Подписка на собственные входящие звонки (SSE) + окно на любом экране оболочки. */}
      <ActiveCallProvider enabled={canSubscribeToCalls}>
        <div className="flex h-screen overflow-hidden max-md:[&>aside:first-child]:w-14">
          <Sidebar allowedSlugs={allowedSlugs} userName={userName} roleTitle={roleTitle} />
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <Topbar crumbs={crumbs} headerActions={headerActions} />
            {/* Вертикальный скролл на уровне оболочки: страницы без своего overflow-контейнера
                (справочники и т.п.) прокручиваются здесь; страницы со своим <main overflow-auto>
                (доска сделок) скроллят сами — вложенный скролл корректен. min-h-0 нужен, чтобы
                flex-потомок реально получил скролл, а не растягивал родителя (типовой flexbox-гоча). */}
            <div className="flex min-h-0 min-w-0 flex-1 overflow-y-auto">{children}</div>
          </div>
          <ChatsPanel />
        </div>
      </ActiveCallProvider>
    </CurrencyProvider>
  );
}
