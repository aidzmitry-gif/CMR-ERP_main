import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ShipmentDocumentDraft } from "./shipment-document-draft";

const emptyResponse = () => ({
  status: "draft_required" as const,
  document_kind: "ttn" as const,
  document_label: "ТТН",
  source: { source_key: "12345678-1234-4234-8234-123456789012", digest: "a".repeat(64) },
  prefilled: { operation_date: "2026-09-13", total_quantity: "1", items: [{ line_no: 1, sku_code: "A", quantity: "1" }] },
  required_fields: ["vehicle_registration"],
  blockers: ["Внутренний акт WMS не является ТН или ТТН."],
  shipment_document_policy: { status: "review_ready" as const, policy_id: 7, effective_from: "2026-09-01", normative_verified: true,
    scenario: { kind: "ttn" as const, exchange_mode: "electronic" as const, form_version: "Synthetic", numbering_rule: "Synthetic", signing_rule: "Synthetic", exchange_rule: "Synthetic", evidence: "Synthetic evidence" } },
  saved_revision: 0,
  saved_fields: { sender_legal_entity: "", recipient_legal_entity: "", contract_reference: "", document_number: "", document_date: "",
    carrier: "", vehicle_registration: "", driver: "", route: "", loading_point: "", unloading_point: "",
    items: [{ line_no: 1, unit: "", unit_price: "", vat_basis: "" }] },
  saved_by: null,
  saved_at: null,
  history: [],
  source_history_current: true,
  statutory_certified: false as const,
  can_issue: false as const,
});

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

beforeEach(() => {
  vi.stubGlobal("crypto", { randomUUID: () => "11111111-1111-4111-8111-111111111111" });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(emptyResponse())));
});

it("loads a source-bound non-certified draft and never offers issuance", async () => {
  const user = userEvent.setup();
  render(<ShipmentDocumentDraft org="7" sourceKey="12345678-1234-4234-8234-123456789012" />);
  await user.click(screen.getByRole("button", { name: "Подготовить ТН/ТТН" }));
  expect(await screen.findByText(/Черновик ТТН/)).toBeInTheDocument();
  expect(screen.getByText(/сценарий заполнен/)).toBeInTheDocument();
  expect(screen.getByText(/акт WMS не является ТН\/ТТН/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /выпустить|подписать/i })).not.toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("kind=ttn"), expect.anything()));
});

it("saves and closes only after the server confirms a new version", async () => {
  const user = userEvent.setup();
  let resolvePost: ((value: Response) => void) | undefined;
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation((_input, init) => init?.method === "POST"
    ? new Promise<Response>((resolve) => { resolvePost = resolve; })
    : Promise.resolve(response(emptyResponse())));

  render(<ShipmentDocumentDraft org="7" sourceKey="12345678-1234-4234-8234-123456789012" />);
  await user.click(screen.getByRole("button", { name: "Подготовить ТН/ТТН" }));
  const sender = await screen.findByLabelText("Отправитель (черновые реквизиты)");
  await user.type(sender, "ООО Альфа");
  await user.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("tn-ttn-draft"), expect.objectContaining({ method: "POST" })));
  expect(screen.getByRole("button", { name: "Закрыть подготовку ТН/ТТН" })).toBeInTheDocument();

  const options = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1];
  const request = JSON.parse(String(options?.body)) as { request_key: string; expected_revision: number; source_digest: string; fields: { sender_legal_entity: string } };
  expect(request).toMatchObject({ request_key: "11111111-1111-4111-8111-111111111111", expected_revision: 0, source_digest: "a".repeat(64) });
  expect(request.fields.sender_legal_entity).toBe("ООО Альфа");
  resolvePost?.(response({ ...emptyResponse(), saved_revision: 1, saved_by: "tester", saved_at: "2026-09-13T10:00:00Z", saved_fields: request.fields,
    history: [{ id: 1, revision: 1, actor: "tester", created_at: "2026-09-13T10:00:00Z", fields: request.fields, changes: [] }] }));
  expect(await screen.findByRole("button", { name: "Подготовить ТН/ТТН" })).toBeInTheDocument();
});

it("keeps unsaved input open on conflict and shows immutable before/after history", async () => {
  const user = userEvent.setup();
  const initial = {
    ...emptyResponse(), saved_revision: 2,
    saved_fields: { ...emptyResponse().saved_fields, sender_legal_entity: "ООО Гамма" },
    history: [{ id: 2, revision: 2, actor: "accountant", created_at: "2026-09-13T11:00:00Z",
      fields: { sender_legal_entity: "ООО Гамма" },
      changes: [{ field: "sender_legal_entity", before: "ООО Альфа", after: "ООО Гамма" }] }],
  };
  const refreshed = {
    ...initial, saved_revision: 3,
    saved_fields: { ...initial.saved_fields, recipient_legal_entity: "ООО Дельта" },
    history: [...initial.history, { id: 3, revision: 3, actor: "manager", created_at: "2026-09-13T12:00:00Z",
      fields: { recipient_legal_entity: "ООО Дельта" },
      changes: [{ field: "recipient_legal_entity", before: "", after: "ООО Дельта" }] }],
  };
  let getCount = 0;
  let postCount = 0;
  const postedBodies: Array<{ expected_revision: number; fields: { sender_legal_entity: string; recipient_legal_entity: string } }> = [];
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation((_input, init) => {
    if (init?.method === "POST") {
      postCount += 1;
      const posted = JSON.parse(String(init.body)) as { expected_revision: number; fields: { sender_legal_entity: string; recipient_legal_entity: string } };
      postedBodies.push(posted);
      return Promise.resolve(postCount === 1
        ? response({ detail: "TN/TTN draft changed; reload history before saving another version" }, 409)
        : response({ ...refreshed, saved_revision: 4, saved_by: "accountant", saved_at: "2026-09-13T13:00:00Z", saved_fields: posted.fields }));
    }
    getCount += 1;
    return Promise.resolve(response(getCount === 1 ? initial : refreshed));
  });

  render(<ShipmentDocumentDraft org="7" sourceKey="12345678-1234-4234-8234-123456789012" />);
  await user.click(screen.getByRole("button", { name: "Подготовить ТН/ТТН" }));
  expect(await screen.findByDisplayValue("ООО Гамма")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "История изменений (1)" }));
  expect(screen.getByText(/ООО Альфа → ООО Гамма/)).toBeInTheDocument();
  expect(screen.getByText(/accountant · 2026-09-13T11:00:00Z/)).toBeInTheDocument();

  const sender = screen.getByLabelText("Отправитель (черновые реквизиты)");
  await user.clear(sender); await user.type(sender, "Несохранённый ввод");
  await user.click(screen.getByRole("button", { name: "Сохранить редакцию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/параллельная редакция/i);
  expect(screen.getByRole("button", { name: "Закрыть подготовку ТН/ТТН" })).toBeInTheDocument();
  expect(screen.getByDisplayValue("Несохранённый ввод")).toBeInTheDocument();
  expect(screen.getByDisplayValue("ООО Дельта")).toBeInTheDocument();
  expect(screen.getByText(/редакция 3/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Сохранить редакцию" }));
  await waitFor(() => expect(postedBodies).toHaveLength(2));
  expect(postedBodies[1]).toMatchObject({ expected_revision: 3, fields: { sender_legal_entity: "Несохранённый ввод", recipient_legal_entity: "ООО Дельта" } });
});
