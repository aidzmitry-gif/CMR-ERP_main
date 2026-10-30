import { expect,type Page } from "@playwright/test";

/** Configure the synthetic installation through the same Settings API as the UI. */
export async function configureInstallationCompany(page: Pick<Page, "request">, organizationId: number) {
  const current = await page.request.get("/api/system/installation-organization");
  expect(current.ok(), await current.text()).toBeTruthy();
  const state = await current.json();
  const response = await page.request.put("/api/system/installation-organization", {
    data: { organization_id: organizationId, expected_revision: state.revision, request_id: crypto.randomUUID() },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const configured = await page.request.get("/api/system/instance-organization");
  expect(configured.ok(), await configured.text()).toBeTruthy();
  expect((await configured.json()).organization.id).toBe(organizationId);
}
