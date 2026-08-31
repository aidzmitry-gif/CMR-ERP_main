// Приведение realm-ролей Keycloak к единственной роли интерфейса.
// Технические роли Keycloak (например, uma_authorization) никогда не должны
// становиться ролью ERP по принципу "первая в списке".

export const ONBOARDING_ROLE = "onboarding";

// Порядок намеренно безопасный: если в токене временно одновременно оказались
// onboarding и рабочая роль, сотрудник остаётся в изолированном ознакомлении.
const APP_ROLE_PRIORITY = [
  ONBOARDING_ROLE,
  "admin",
  "director",
  "commercial",
  "assistant",
  "sales_head",
  "sales",
  "sales_manager",
  "sales_cli",
  "procurement",
  "warehouse",
  "logistics",
  "production",
  "finance",
  "hr",
] as const;

/**
 * Выбрать только известную роль приложения. Неизвестные/технические realm-роли
 * дают минимальную роль onboarding, а не административный fallback.
 */
export function resolveAppRole(realmRoles: readonly string[]): string {
  return APP_ROLE_PRIORITY.find((role) => realmRoles.includes(role)) ?? ONBOARDING_ROLE;
}

export function isOnboardingRole(role: string | null | undefined): boolean {
  return role === ONBOARDING_ROLE;
}

/** Единственная стартовая страница для роли без данных. */
export function defaultPathForRole(role: string | null | undefined): string {
  return isOnboardingRole(role) ? "/onboarding" : "/crm/deals";
}
