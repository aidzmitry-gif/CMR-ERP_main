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
  saved_fields: { sender_legal_entity: "Synthetic test company", recipient_legal_entity: "", contract_reference: "", document_number: "", document_date: "",
    sender_identity: { reference: "accounting.organization", id: 7, name: "Synthetic test company", unp: "999999999" }, recipient_identity: null,
    carrier: "", vehicle_registration: "", driver: "", route: "", loading_point: "", unloading_point: "",
    items: [{ line_no: 1, unit: "", unit_price: "", vat_basis: "" }] },
  saved_by: null,
  saved_at: null,
  history: [],
  source_history_current: true,
  directory_identity_status: "recipient_required" as const,
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
  expect(await screen.findByDisplayValue("Synthetic test company")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Сохранить и закрыть" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: /выпустить|подписать/i })).not.toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("kind=ttn"), expect.anything()));
});

it("saves and closes only after the server confirms a new version", async () => {
  const user = userEvent.setup();
  let resolvePost: ((value: Response) => void) | undefined;
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation((input, init) => {
    if (init?.method === "POST") return new Promise<Response>((resolve) => { resolvePost = resolve; });
    if (String(input).includes("sales/buyers")) return Promise.resolve(response({ organization_id: 7,
      items: [{ id: 31, name: "ООО Покупатель", unp: "123456789", revision: 4 }], truncated: false }));
    return Promise.resolve(response(emptyResponse()));
  });

  render(<ShipmentDocumentDraft org="7" sourceKey="12345678-1234-4234-8234-123456789012" />);
  await user.click(screen.getByRole("button", { name: "Подготовить ТН/ТТН" }));
  await user.type(await screen.findByLabelText("Поиск получателя в справочнике"), "Покупатель");
  await user.click(screen.getByRole("button", { name: "Найти получателя" }));
  await screen.findByRole("option", { name: /ООО Покупатель/ });
  await user.selectOptions(screen.getByLabelText("Получатель из справочника"), "31");
  await user.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("tn-ttn-draft"), expect.objectContaining({ method: "POST" })));
  expect(screen.getByRole("button", { name: "Закрыть подготовку ТН/ТТН" })).toBeInTheDocument();

  const options = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1];
  const request = JSON.parse(String(options?.body)) as { request_key: string; expected_revision: number; source_digest: string; fields: { recipient_counterparty_id: number; recipient_counterparty_revision: number } };
  expect(request).toMatchObject({ request_key: "11111111-1111-4111-8111-111111111111", expected_revision: 0, source_digest: "a".repeat(64) });
  expect(request.fields).toMatchObject({ recipient_counterparty_id: 31, recipient_counterparty_revision: 4 });
  const savedFields = { ...emptyResponse().saved_fields, sender_legal_entity: "Synthetic test company",
    recipient_legal_entity: "ООО Покупатель", recipient_identity: { reference: "core.counterparties", id: 31, name: "ООО Покупатель", unp: "123456789", revision: 4 } };
  resolvePost?.(response({ ...emptyResponse(), saved_revision: 1, saved_by: "tester", saved_at: "2026-09-13T10:00:00Z", saved_fields: savedFields,
    directory_identity_status: "verified", history: [{ id: 1, revision: 1, actor: "tester", created_at: "2026-09-13T10:00:00Z", fields: savedFields, changes: [] }] }));
  expect(await screen.findByRole("button", { name: "Подготовить ТН/ТТН" })).toBeInTheDocument();
});

it("keeps unsaved input open on conflict and shows immutable before/after history", async () => {
  const user = userEvent.setup();
  const initial = {
    ...emptyResponse(), saved_revision: 2,
    directory_identity_status: "verified" as const,
    saved_fields: { ...emptyResponse().saved_fields, document_number: "Номер 2", recipient_legal_entity: "ООО Гамма",
      recipient_identity: { reference: "core.counterparties", id: 7, name: "ООО Гамма", unp: "111111111", revision: 2 } },
    history: [{ id: 2, revision: 2, actor: "accountant", created_at: "2026-09-13T11:00:00Z",
      fields: { document_number: "Номер 2" },
      changes: [{ field: "document_number", before: "Номер 1", after: "Номер 2" }] }],
  };
  const refreshed = {
    ...initial, saved_revision: 3,
    saved_fields: { ...initial.saved_fields, contract_reference: "Изменённый удалённо" },
    history: [...initial.history, { id: 3, revision: 3, actor: "manager", created_at: "2026-09-13T12:00:00Z",
      fields: { contract_reference: "Изменённый удалённо" },
      changes: [{ field: "contract_reference", before: "Договор", after: "Изменённый удалённо" }] }],
  };
  let getCount = 0;
  let postCount = 0;
  const postedBodies: Array<{ expected_revision: number; fields: { document_number: string; recipient_counterparty_id: number; recipient_counterparty_revision: number } }> = [];
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation((_input, init) => {
    if (init?.method === "POST") {
      postCount += 1;
      const posted = JSON.parse(String(init.body)) as { expected_revision: number; fields: { document_number: string; recipient_counterparty_id: number; recipient_counterparty_revision: number } };
      postedBodies.push(posted);
      return Promise.resolve(postCount === 1
        ? response({ detail: "TN/TTN draft changed; reload history before saving another version" }, 409)
        : response({ ...refreshed, saved_revision: 4, saved_by: "accountant", saved_at: "2026-09-13T13:00:00Z", saved_fields: { ...refreshed.saved_fields, document_number: posted.fields.document_number } }));
    }
    getCount += 1;
    return Promise.resolve(response(getCount === 1 ? initial : refreshed));
  });

  render(<ShipmentDocumentDraft org="7" sourceKey="12345678-1234-4234-8234-123456789012" />);
  await user.click(screen.getByRole("button", { name: "Подготовить ТН/ТТН" }));
  expect(await screen.findByLabelText("Получатель из справочника")).toHaveValue("7");
  await user.click(screen.getByRole("button", { name: "История изменений (1)" }));
  expect(screen.getByText(/Номер 1 → Номер 2/)).toBeInTheDocument();
  expect(screen.getByText(/accountant · 2026-09-13T11:00:00Z/)).toBeInTheDocument();

  const number = screen.getByLabelText("Черновой номер (не официальный)");
  await user.clear(number); await user.type(number, "Несохранённый ввод");
  await user.click(screen.getByRole("button", { name: "Сохранить редакцию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/параллельная редакция/i);
  expect(screen.getByRole("button", { name: "Закрыть подготовку ТН/ТТН" })).toBeInTheDocument();
  expect(screen.getByDisplayValue("Несохранённый ввод")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Изменённый удалённо")).toBeInTheDocument();
  expect(screen.getByText(/редакция 3/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Сохранить редакцию" }));
  await waitFor(() => expect(postedBodies).toHaveLength(2));
  expect(postedBodies[1]).toMatchObject({ expected_revision: 3, fields: {
    document_number: "Несохранённый ввод", recipient_counterparty_id: 7, recipient_counterparty_revision: 2,
  } });
});
