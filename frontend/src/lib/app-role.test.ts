import { describe, expect, it } from "vitest";

import { defaultPathForRole, resolveAppRole } from "@/lib/app-role";

describe("resolveAppRole", () => {
  it("игнорирует технические realm-роли Keycloak", () => {
    expect(resolveAppRole(["offline_access", "uma_authorization"])).toBe("onboarding");
  });

  it("оставляет сотрудника в onboarding, пока эта роль присутствует", () => {
    expect(resolveAppRole(["uma_authorization", "sales", "onboarding"])).toBe("onboarding");
  });

  it("выбирает известную рабочую роль, а не порядок realm_access.roles", () => {
    expect(resolveAppRole(["uma_authorization", "sales_head", "sales"])).toBe("sales_head");
  });

  it("сохраняет известные alias и dev суперроль в allowlist", () => {
    expect(resolveAppRole(["uma_authorization", "sales_manager"])).toBe("sales_manager");
    expect(resolveAppRole(["admin"])).toBe("admin");
  });

  it("ведёт onboarding только на изолированную страницу", () => {
    expect(defaultPathForRole("onboarding")).toBe("/onboarding");
    expect(defaultPathForRole("sales")).toBe("/crm/deals");
  });

  it("ведёт ограниченного оператора в приглашения, сохраняя приоритет onboarding", () => {
    const role = resolveAppRole(["director", "crm_invitation_operator"]);
    expect(role).toBe("crm_invitation_operator");
    expect(defaultPathForRole(role)).toBe("/erp/settings/invitations");
    expect(resolveAppRole(["onboarding", role])).toBe("onboarding");
  });
});
