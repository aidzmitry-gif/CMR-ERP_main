import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { OfficeReviewQueue } from "./office-review-queue";

const queue = {
  documents: [{ id: 4, number: "DRAFT-4", title: "Draft", company: "Synthetic Company", assignment_revision: 2, reviewer_subject: null }],
  reviewers: [{ subject: "stable-reviewer", name: "Synthetic Reviewer" }],
};
function ok(data: unknown) { return { ok: true, status: 200, json: async () => data }; }
afterEach(() => vi.unstubAllGlobals());
async function fill() {
  await screen.findByRole("option", { name: /DRAFT-4/ });
  fireEvent.change(screen.getByLabelText("Черновик"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("Проверяющий"), { target: { value: "stable-reviewer" } });
  fireEvent.change(screen.getByLabelText("Основание назначения"), { target: { value: "Synthetic reason" } });
}

it("does not expose assignment controls when access is denied", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 403 })));
  render(<OfficeReviewQueue />);
  expect(await screen.findByText(/Назначать проверяющего может только руководитель/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Назначить проверяющего" })).not.toBeInTheDocument();
});

it("shows empty state without invented documents", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ok({ documents: [], reviewers: [] })));
  render(<OfficeReviewQueue />);
  expect(await screen.findByText("Нет черновиков для назначения.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Черновик")).not.toBeInTheDocument();
});

it("assigns the selected stable identity and exact observed revision, then reads back", async () => {
  let reads = 0;
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === "POST") return ok({ document_id: 4, subject: "stable-reviewer", assignment_revision: 3 });
    reads++;
    return ok(reads === 1 ? queue : { ...queue, documents: [{ ...queue.documents[0], reviewer_subject: "stable-reviewer", assignment_revision: 3 }] });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<OfficeReviewQueue />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Назначить проверяющего" }));
  expect(await screen.findByText(/Проверяющий назначен/)).toBeInTheDocument();
  await waitFor(() => expect(reads).toBe(2));
  const post = fetcher.mock.calls.find(([, options]) => options?.method === "POST");
  expect(post?.[0]).toBe("/api/office/docs/4/shipping-reviewer");
  expect(JSON.parse(post?.[1]?.body as string)).toEqual({ subject: "stable-reviewer", expected_revision: 2, evidence: "Synthetic reason" });
});

it("blocks stale assignment until an explicit refreshed read", async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => options?.method === "POST" ? { ok: false, status: 409 } : ok(queue));
  vi.stubGlobal("fetch", fetcher);
  render(<OfficeReviewQueue />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Назначить проверяющего" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Назначение уже изменилось");
  expect(screen.getByRole("button", { name: "Назначить проверяющего" })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
  await waitFor(() => expect(screen.getByLabelText("Черновик")).toBeEnabled());
  expect(screen.getByLabelText("Черновик")).toHaveValue("");
});

it("does not retry an ambiguous network result", async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === "POST") throw new Error("network");
    return ok(queue);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<OfficeReviewQueue />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Назначить проверяющего" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Результат назначения неизвестен");
  expect(screen.getByRole("button", { name: "Назначить проверяющего" })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
});

it("does not accept a success response for another document", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options?: RequestInit) => options?.method === "POST" ? ok({ document_id: 999, subject: "stable-reviewer", assignment_revision: 3 }) : ok(queue)));
  render(<OfficeReviewQueue />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Назначить проверяющего" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Результат назначения неизвестен");
  expect(screen.queryByText(/Проверяющий назначен/)).not.toBeInTheDocument();
});
