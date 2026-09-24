import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { useUnsavedDocumentGuard } from "./use-unsaved-document-guard";

afterEach(() => vi.unstubAllGlobals());

it("blocks internal links and reload while unsaved, then releases them after save", () => {
  const confirm = vi.fn(() => false);
  const navigate = vi.fn();
  vi.stubGlobal("confirm", confirm);
  function Editor({ pending }: { pending: boolean }) {
    useUnsavedDocumentGuard(pending);
    return <a href="/erp/accounting" onClick={(event) => { event.preventDefault(); navigate(); }}>Бухгалтерия</a>;
  }
  const view = render(<Editor pending={false} />);
  fireEvent.click(screen.getByRole("link", { name: "Бухгалтерия" }));
  expect(navigate).toHaveBeenCalledTimes(1);
  expect(confirm).not.toHaveBeenCalled();

  view.rerender(<Editor pending />);
  const blocked = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
  screen.getByRole("link", { name: "Бухгалтерия" }).dispatchEvent(blocked);
  expect(blocked.defaultPrevented).toBe(true);
  expect(navigate).toHaveBeenCalledTimes(1);
  expect(confirm).toHaveBeenCalledTimes(1);
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);

  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("link", { name: "Бухгалтерия" }));
  expect(navigate).toHaveBeenCalledTimes(2);
  view.rerender(<Editor pending={false} />);
  const afterSave = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(afterSave);
  expect(afterSave.defaultPrevented).toBe(false);
});
