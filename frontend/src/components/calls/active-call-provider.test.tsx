import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ActiveCallProvider } from "./active-call-provider";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";

const mocks = vi.hoisted(() => ({
  push: vi.fn(), refresh: vi.fn(), subscribeCalls: vi.fn(), createLead: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }) }));
vi.mock("@/components/calls/call-window", () => ({ CallWindow: () => null }));
vi.mock("@/lib/api", () => ({
  subscribeCalls: mocks.subscribeCalls, createLead: mocks.createLead,
  callComment: vi.fn(), callLinkDeal: vi.fn(), callResult: vi.fn(),
}));

function DirtyDocument() {
  useUnsavedDocumentGuard(true);
  return <p>Черновик накладной</p>;
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("does not jump from an unsaved receipt to a deal in the incoming-call popup", async () => {
  mocks.subscribeCalls.mockImplementation((_owner, onCard) => {
    onCard({ id: 1, call_id: "c1", direction: "in", phone: "+375291112233",
      owner: "Иванов", deal_id: 7, status: "ringing" });
    return () => {};
  });
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<ActiveCallProvider owner="Иванов"><DirtyDocument /></ActiveCallProvider>);
  fireEvent.click(await screen.findByRole("button", { name: /Сделка #7/ }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(mocks.push).not.toHaveBeenCalled();
  expect(screen.getByText("Черновик накладной")).toBeInTheDocument();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: /Сделка #7/ }));
  expect(mocks.push).toHaveBeenCalledWith("/crm/deals/7");
});

it("does not create a lead before the user accepts leaving an unsaved receipt", async () => {
  mocks.subscribeCalls.mockImplementation((_owner, onCard) => {
    onCard({ id: 2, call_id: "c2", direction: "in", phone: "+375291112233",
      owner: "", deal_id: null, status: "ringing" });
    return () => {};
  });
  vi.stubGlobal("confirm", vi.fn(() => false));
  render(<ActiveCallProvider owner="Иванов"><DirtyDocument /></ActiveCallProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Создать лид" }));
  expect(mocks.createLead).not.toHaveBeenCalled();
  expect(mocks.push).not.toHaveBeenCalled();
});
