import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { ActiveCallProvider } from "./active-call-provider";
import type { CallCard } from "@/lib/api";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";

const mocks = vi.hoisted(() => ({
  push: vi.fn(), refresh: vi.fn(), subscribeCalls: vi.fn(), createLead: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }) }));
vi.mock("@/components/calls/call-window", () => ({
  CallWindow: ({ context }: { context?: unknown }) => (
    <div data-testid="call-window-state">{context ? "open" : "closed"}</div>
  ),
}));
vi.mock("@/lib/api", () => ({
  subscribeCalls: mocks.subscribeCalls, createLead: mocks.createLead,
  callComment: vi.fn(), callLinkDeal: vi.fn(), callResult: vi.fn(),
}));

function DirtyDocument() {
  useUnsavedDocumentGuard(true);
  return <p>Черновик накладной</p>;
}

function PersistentChild() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount((value) => value + 1)}>Child count {count}</button>;
}

function sampleCall(id: number): CallCard {
  return {
    id,
    call_id: `c${id}`,
    direction: "in",
    phone: "+375291112233",
    owner: "Иванов",
    deal_id: id,
    status: "ringing",
  };
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("does not jump from an unsaved receipt to a deal in the incoming-call popup", async () => {
  mocks.subscribeCalls.mockImplementation((onCard) => {
    onCard({ id: 1, call_id: "c1", direction: "in", phone: "+375291112233",
      owner: "Иванов", deal_id: 7, status: "ringing" });
    return () => {};
  });
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<ActiveCallProvider enabled><DirtyDocument /></ActiveCallProvider>);
  fireEvent.click(await screen.findByRole("button", { name: /Сделка #7/ }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(mocks.push).not.toHaveBeenCalled();
  expect(screen.getByText("Черновик накладной")).toBeInTheDocument();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: /Сделка #7/ }));
  expect(mocks.push).toHaveBeenCalledWith("/crm/deals/7");
});

it("does not create a lead before the user accepts leaving an unsaved receipt", async () => {
  mocks.subscribeCalls.mockImplementation((onCard) => {
    onCard({ id: 2, call_id: "c2", direction: "in", phone: "+375291112233",
      owner: "", deal_id: null, status: "ringing" });
    return () => {};
  });
  vi.stubGlobal("confirm", vi.fn(() => false));
  render(<ActiveCallProvider enabled><DirtyDocument /></ActiveCallProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Создать лид" }));
  expect(mocks.createLead).not.toHaveBeenCalled();
  expect(mocks.push).not.toHaveBeenCalled();
});

it("PROVIDER-DISABLED defaults to no subscription while preserving children", () => {
  render(<ActiveCallProvider><p>Shell content</p></ActiveCallProvider>);
  expect(screen.getByText("Shell content")).toBeInTheDocument();
  expect(screen.queryByTestId("call-window-state")).not.toBeInTheDocument();
  expect(mocks.subscribeCalls).not.toHaveBeenCalled();
});

it("PROVIDER-ENABLED-UNMOUNT subscribes once and cleans up on unmount", () => {
  const unsubscribe = vi.fn();
  mocks.subscribeCalls.mockReturnValue(unsubscribe);
  const view = render(<ActiveCallProvider enabled><p>Shell content</p></ActiveCallProvider>);
  expect(mocks.subscribeCalls).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Shell content")).toBeInTheDocument();
  view.unmount();
  expect(unsubscribe).toHaveBeenCalledTimes(1);
});

it("PROVIDER-TOGGLE-LATE clears old UI, ignores late events, and starts one fresh subscription", async () => {
  const callbacks: Array<(card: CallCard) => void> = [];
  const unsubscribes = [vi.fn(), vi.fn()];
  mocks.subscribeCalls.mockImplementation((onCard: (card: CallCard) => void) => {
    callbacks.push(onCard);
    return unsubscribes[callbacks.length - 1];
  });

  const view = render(<ActiveCallProvider enabled><PersistentChild /></ActiveCallProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Child count 0" }));
  expect(screen.getByRole("button", { name: "Child count 1" })).toBeInTheDocument();
  act(() => callbacks[0](sampleCall(7)));
  fireEvent.click(await screen.findByRole("button", { name: /Принять/ }));
  expect(screen.getByTestId("call-window-state")).toHaveTextContent("open");

  view.rerender(<ActiveCallProvider enabled={false}><PersistentChild /></ActiveCallProvider>);
  expect(unsubscribes[0]).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId("call-window-state")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Child count 1" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Сделка #7/ })).not.toBeInTheDocument();
  act(() => callbacks[0](sampleCall(8)));
  expect(screen.queryByRole("button", { name: /Сделка #8/ })).not.toBeInTheDocument();

  view.rerender(<ActiveCallProvider enabled><PersistentChild /></ActiveCallProvider>);
  expect(mocks.subscribeCalls).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId("call-window-state")).toHaveTextContent("closed");
  act(() => callbacks[1](sampleCall(9)));
  expect(await screen.findByRole("button", { name: /Сделка #9/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Child count 1" })).toBeInTheDocument();
  view.unmount();
  expect(unsubscribes[1]).toHaveBeenCalledTimes(1);
});
