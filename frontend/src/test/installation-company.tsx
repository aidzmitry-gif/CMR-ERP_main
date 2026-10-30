import { act,render as rtlRender,screen,type RenderResult } from "@testing-library/react";
import { Fragment,type ReactElement } from "react";

// Business-component tests supply installation configuration independently of
// their module API fixtures. The real gate/resolver have separate contract tests.
let companyId: number | null = 1;
let revision = 0;
let current: { element: ReactElement; view: RenderResult } | null = null;
export function resetCompany(id: number) { companyId = id; revision = 0; current = null; }
export async function fetchTestInstanceOrganization() {
  if (!companyId) throw new Error("Юрлицо установки не настроено. Проверьте настройки установки.");
  return { id: companyId, name: `Юрлицо установки ${companyId}`, unp: "987654321" };
}
export function render(element: ReactElement) {
  const view = rtlRender(<Fragment key={revision}>{element}</Fragment>);
  current = { element, view };
  return { ...view, rerender(next: ReactElement) {
    if (current) current.element = next;
    view.rerender(<Fragment key={revision}>{next}</Fragment>);
  } };
}
export async function waitForCompany() {
  return screen.findAllByText(new RegExp(`Юрлицо установки ${companyId} ·`));
}
/** A changed installation setting takes effect on a fresh page, never a module picker. */
export async function configureCompany(value: string | number) {
  const next = Number(value) || null;
  if (next !== companyId) {
    companyId = next;
    if (current) {
      const { element, view } = current;
      await act(async () => { view.rerender(<Fragment key={++revision}>{element}</Fragment>); });
    }
  }
  if (current && companyId) await waitForCompany();
}
