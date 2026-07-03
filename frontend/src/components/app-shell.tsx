import { redirect } from "next/navigation";

import { ActiveCallProvider } from "@/components/calls/active-call-provider";
import { ChatsPanel } from "@/components/chats-panel";
import { CurrencyProvider } from "@/components/kanban/currency-context";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { fetchAccess } from "@/lib/access";
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
