import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingShipmentPreview } from "./accounting-shipment-preview";

const key = "00000000-0000-4000-8000-000000000001";
const source = `wms:physical-shipment:1:${key}`;
const snapshot = { digest: "a".repeat(64), source_key: key, snapshot: { organization_id: 1, document_id: 27, operation_date: "2026-09-01", lines: [{ source: "line1", line_no: 7, warehouse: "W", sku_code: "A", qty: "0.000001" }] } };
const accounts = ["41.2", "90.4", "62", "90.1", "90.2", "68.2"].map(code => ({ code, title: code, required_dimensions: code === "90.4" ? ["order"] : [] }));
const props = { org: "1", source, accounts, date: "2026-09-01", policyId: 3, disabled: false, onDate: vi.fn() };
const calculation = { organization_id: 1, source, status: "preview", posted: false, net_byn: "20.00", vat_byn: "4.00", gross_byn: "24.00", mapping: [{ lot: "L", quantity: "0.000001", cost_byn: "0.00" }], postings: [{ posting: { lines: [{ account: "62", side: "debit", amount: "24.00", quantity: null, dimensions: {} }] } }, { posting: { lines: [{ account: "41.2", side: "credit", amount: "0.01", quantity: "0.000001", dimensions: { lot: "L" } }] } }] };
const reply = (value: unknown) => ({ ok: true, json: async () => value });
afterEach(() => vi.unstubAllGlobals());
it("keeps the exact confirmation available after a parent date change and lost response", async () => {
  const basis = "b".repeat(64);
  let finish!: (value: unknown) => void;
  const fetcher = vi.fn().mockResolvedValueOnce(reply(snapshot))
    .mockResolvedValueOnce(reply({ ...calculation, basis_digest: basis }))
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce(reply({ organization_id: 1, source, posted: true, basis_digest: basis, receipt_id: 4, entry_ids: [8] }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AccountingShipmentPreview {...props} />);
  await completeForm();
  fireEvent.click(screen.getByText("Рассчитать проводки отгрузки"));
  fireEvent.click(await screen.findByText("Подтвердить проводки отгрузки"));
  expect(screen.getByLabelText("Партия 1")).toBeDisabled();
  expect(screen.getByText("Проверить сохранённый черновик")).toBeDisabled();
  const sent = JSON.parse(fetcher.mock.calls[2][1].body);
  expect(sent).toEqual({ ...JSON.parse(fetcher.mock.calls[1][1].body), expected_basis_digest: basis });
  view.rerender(<AccountingShipmentPreview {...props} date="2026-09-02" />);
  await act(async () => finish({ ok: false, status: 503, json: async () => ({}) }));
  fireEvent.click(await screen.findByText("Повторить подтверждение"));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4));
  expect(fetcher.mock.calls[2]).toEqual(fetcher.mock.calls[3]);
  await waitFor(() => expect(screen.getByLabelText("Партия 1")).not.toBeDisabled());
});
function fill(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
async function completeForm() {
  await screen.findByLabelText("Партия 1");
  for (const [label,value] of Object.entries({ "Дата первичного документа": "2026-09-01", "Содержание операции": "Отгрузка", "Основание признания выручки": "Договор", "Основание соответствия единиц": "Штуки", "Распределение стоимости": "cumulative_floor_last", "Округление НДС": "commercial_line_half_up", "Счёт запасов 1": "41.2", "Партия 1": "L", "Счёт себестоимости 1": "90.4", "Расход 1 · Заказ": "Z", "Без НДС, BYN · строка 7": "20.00", "Ставка НДС, % · строка 7": "20", "Основание НДС · строка 7": "Проверено", "Покупатель · строка 7": "62", "Выручка · строка 7": "90.1", "НДС из выручки · строка 7": "90.2", "НДС к уплате · строка 7": "68.2", "Покупатель строки 7 · Контрагент": "Buyer", "Покупатель строки 7 · Договор": "C" })) fill(label,value);
}

it("sends explicit decisions and exact quantities against the trusted act, then invalidates changed inputs", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(reply(snapshot)).mockResolvedValueOnce(reply(calculation));
  vi.stubGlobal("fetch",fetcher);
  render(<AccountingShipmentPreview {...props} />);
  await completeForm();
  expect(screen.getByLabelText("Покупатель строки 7 · Документ расчётов")).toHaveValue("Счёт № 27");
  fireEvent.click(screen.getByText("Рассчитать проводки отгрузки"));
  expect(await screen.findByRole("region", { name: "Расчёт отгрузки" })).toHaveTextContent("Себестоимость 0.00 BYN");
  const [url,options] = fetcher.mock.calls[1];
  expect(url).toBe(`/api/accounting/organizations/1/shipments/${key}/preview`);
  const body = JSON.parse(options.body);
  expect(body).toMatchObject({ expected_act_digest: snapshot.digest, policy_id: 3, posting_date: "2026-09-01", allocations: [{ line_source: "line1", quantity: "0.000001", expense_dimensions: { order: "Z" } }], commercial_lines: [{ line_no: 7, net_amount: "20.00", vat_rate: "20", buyer_dimensions: { settlement_document: "sales:document:27" } }] });
  expect(body).not.toHaveProperty("snapshot");
  fill("Страница проводок","1");
  expect(screen.getByRole("region", { name: "Расчёт отгрузки" })).toHaveTextContent("0.01");
  fill("Партия 1","Changed");
  expect(screen.queryByRole("region", { name: "Расчёт отгрузки" })).not.toBeInTheDocument();
});

it("does not assume a VAT rate or rounding decision and rejects a foreign snapshot", async () => {
  const fetcher = vi.fn().mockResolvedValue(reply(snapshot)); vi.stubGlobal("fetch",fetcher);
  const view = render(<AccountingShipmentPreview {...props} />);
  await screen.findByLabelText("Партия 1");
  expect(screen.getByLabelText("Ставка НДС, % · строка 7")).toHaveValue("");
  fireEvent.click(screen.getByText("Рассчитать проводки отгрузки"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Заполните");
  expect(fetcher).toHaveBeenCalledTimes(1);
  view.unmount();
  fetcher.mockResolvedValue(reply({ ...snapshot, snapshot: { ...snapshot.snapshot, organization_id: 2 } }));
  render(<AccountingShipmentPreview {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("другого источника");
  expect(screen.queryByLabelText("Партия 1")).not.toBeInTheDocument();
});

it("covers repeated invoice lines once commercially and supports splitting physical quantities", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply({ ...snapshot, snapshot: { ...snapshot.snapshot, lines: [...snapshot.snapshot.lines, { ...snapshot.snapshot.lines[0], source: "line2", warehouse: "W2" }] } })));
  render(<AccountingShipmentPreview {...props} />);
  await screen.findByLabelText("Партия 2");
  expect(screen.getAllByRole("group", { name: "Продажа строки 7" })).toHaveLength(1);
  fireEvent.click(screen.getByText("Добавить партию для строки 7 · W"));
  fill("Количество 1","0.000000"); fill("Количество 3","0.000001");
  expect(screen.getByLabelText("Количество 2")).toHaveValue("0.000001");
  fireEvent.click(screen.getByText("Удалить распределение 1"));
  expect(screen.getAllByLabelText(/^Партия \d/)).toHaveLength(2);
});

it("withholds late calculations after the posting date changes", async () => {
  let resolve!: (value: unknown) => void;
  const fetcher = vi.fn().mockResolvedValueOnce(reply(snapshot)).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  vi.stubGlobal("fetch",fetcher);
  const view = render(<AccountingShipmentPreview {...props} />);
  await completeForm(); fireEvent.click(screen.getByText("Рассчитать проводки отгрузки"));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  view.rerender(<AccountingShipmentPreview {...props} date="2026-09-02" />);
  expect(screen.queryByText("Рассчитывается весь акт…")).not.toBeInTheDocument();
  expect(screen.getByText("Рассчитать проводки отгрузки")).not.toBeDisabled();
  await act(async () => resolve(reply(calculation)));
  expect(screen.queryByRole("region", { name: "Расчёт отгрузки" })).not.toBeInTheDocument();
  view.rerender(<AccountingShipmentPreview {...props} />);
  expect(screen.queryByRole("region", { name: "Расчёт отгрузки" })).not.toBeInTheDocument();
});

it.each(["changed_act", "malformed_row"])("does not replace inputs from an invalid draft: %s", async (caseName) => {
  const payload = { act_digest: caseName === "changed_act" ? "b".repeat(64) : snapshot.digest, posting_date: props.date, policy_id: 3,
    form: {document_date:"",explanation:"",recognition_basis:"",unit_basis:"",cost_allocation:"",vat_rounding:""}, allocations:[{line_source:"foreign"}], terms:[] };
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(reply(snapshot)).mockResolvedValueOnce(reply({revision:1,draft:{organization_id:1,source,revision:1,payload,actor:"Other",created_at:"2026-09-10"}})));
  render(<AccountingShipmentPreview {...props}/>);
  await screen.findByLabelText("Партия 1"); fill("Партия 1","Keep mine");
  fireEvent.click(screen.getByText("Проверить сохранённый черновик"));
  await screen.findByText("Восстановить сохранённые поля");
  fireEvent.click(screen.getByText("Восстановить сохранённые поля"));
  expect(screen.getByRole("alert")).toHaveTextContent(caseName === "changed_act" ? "другой версии акта" : "не соответствуют акту");
  expect(screen.getByLabelText("Партия 1")).toHaveValue("Keep mine");
  expect(screen.getByText("Сохранить подготовку")).toBeDisabled();
});

it("restores same-date fields without resetting the already loaded accounts and policy", async () => {
  const onDate=vi.fn();
  const payload={act_digest:snapshot.digest,posting_date:props.date,policy_id:3,
    form:{document_date:"",explanation:"Restored",recognition_basis:"",unit_basis:"",cost_allocation:"",vat_rounding:""},
    allocations:[{line_source:"line1",account:"41.2",lot:"Saved lot",quantity:"0.000001",expense_account:"90.4",expense_dimensions:{}}],
    terms:[{line_no:7,net_amount:"",vat_rate:"",vat_basis:"",buyer_account:"",revenue_account:"",vat_revenue_account:"",vat_payable_account:"",buyer_dimensions:{settlement_document:"sales:document:27"},revenue_dimensions:{},vat_dimensions:{}}]};
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(reply(snapshot)).mockResolvedValueOnce(reply({revision:1,draft:{organization_id:1,source,revision:1,payload,actor:"Accountant",created_at:"2026-09-10"}})));
  render(<AccountingShipmentPreview {...props} onDate={onDate}/>);
  await screen.findByLabelText("Партия 1");
  fireEvent.click(screen.getByText("Проверить сохранённый черновик"));
  await screen.findByText("Восстановить сохранённые поля");
  fireEvent.click(screen.getByText("Восстановить сохранённые поля"));
  expect(screen.getByLabelText("Партия 1")).toHaveValue("Saved lot");
  expect(onDate).not.toHaveBeenCalled();
  expect(screen.getByText("Рассчитать проводки отгрузки")).not.toBeDisabled();
});
