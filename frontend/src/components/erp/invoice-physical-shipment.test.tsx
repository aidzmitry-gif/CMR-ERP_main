import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { InvoicePhysicalShipment } from "./invoice-physical-shipment";
import * as api from "@/lib/invoice-physical-shipment-api";
vi.mock("@/lib/invoice-physical-shipment-api",async()=>({...await vi.importActual("@/lib/invoice-physical-shipment-api"),previewShipment:vi.fn(),shipmentIdentity:vi.fn(),shipmentHistory:vi.fn(),createShipment:vi.fn(),findShipment:vi.fn()}));
const scope={organization_id:7,deal_id:3,document_id:11},h="a".repeat(64);
const preview:api.Preview={identity:{organization_id:7,document_id:11,document_version:2,content_sha256:h},reservation_digest:h,remaining_digest:h,physical_digest:h,lines:[1,2].map(line_no=>({execution_mode:"wms" as const,prohibit_negative_stock:true,stock_issue:null,line_no,sku_code:"A",warehouse:"W",original_qty:"3.00",remaining_qty:"3.00",physical:"10.00",reserved:"6.00",free:"4.00",blocking_reason:null}))};
const receipt={act_id:5,snapshot:{operation_date:"2026-01-01",actor:"picker",evidence:"Выдача",lines:[{line_no:1,sku_code:"A",warehouse:"W",qty:"1.00"}]}} as api.Receipt;
const stockIssue:api.StockIssue={code:"stock_shortage",reason:"unknown_stock",message:"Остаток не подтверждён",sku_code:"A",warehouse:"W",requested:"1.00",physical:null,reserved:"0.00",reserved_other:"0.00",available:null,shortage:null};
beforeEach(()=>{vi.resetAllMocks();vi.stubGlobal("crypto",webcrypto);sessionStorage.clear();vi.mocked(api.previewShipment).mockResolvedValue(preview);vi.mocked(api.shipmentIdentity).mockResolvedValue(preview.identity);vi.mocked(api.shipmentHistory).mockResolvedValue({items:[],next_after_id:null});});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
async function confirm(){await screen.findByLabelText("Отгрузить строку 1, склад W");fireEvent.change(screen.getByLabelText("Отгрузить строку 1, склад W"),{target:{value:"1"}});fireEvent.change(screen.getByLabelText("Основание отгрузки"),{target:{value:"Выдача"}});fireEvent.click(screen.getByRole("button",{name:"Проверить выбранную отгрузку"}));fireEvent.click(screen.getByRole("button",{name:"Подтвердить фактическую отгрузку"}));}
it("requires confirmation, persists before POST, shows internal receipt and prevents double click",async()=>{let resolve!:(r:api.Receipt)=>void;vi.mocked(api.createShipment).mockImplementation(p=>{expect(api.loadPending(scope)).toEqual(p);return new Promise(r=>{resolve=r;});});render(<InvoicePhysicalShipment scope={scope}/>);await confirm();expect(api.createShipment).toHaveBeenCalledOnce();expect(screen.getByText(/Не является ТН\/ТТН/)).toBeInTheDocument();await act(async()=>resolve(receipt));expect(await screen.findByText("Складское движение подтверждено внутренним актом; бухгалтерские проводки требуют отдельной сверки.")).toBeInTheDocument();expect(api.loadPending(scope)).toBeNull();});
it("restores unknown after reload, 404 retries exact original body only",async()=>{vi.mocked(api.createShipment).mockRejectedValueOnce(new api.ShipmentError("Связь прервана"));const view=render(<InvoicePhysicalShipment scope={scope}/>);await confirm();await screen.findByText("Связь прервана");const original=api.loadPending(scope)!;view.unmount();render(<InvoicePhysicalShipment scope={scope}/>);vi.mocked(api.findShipment).mockRejectedValue(new api.ShipmentError("missing",404));vi.mocked(api.createShipment).mockResolvedValue(receipt);fireEvent.click(await screen.findByRole("button",{name:"Проверить результат и повторить тот же запрос"}));await screen.findByText("Складское движение подтверждено внутренним актом; бухгалтерские проводки требуют отдельной сверки.");expect(api.createShipment).toHaveBeenLastCalledWith(original);expect(api.previewShipment).toHaveBeenCalledOnce();});
it("resolves committed unknown by key without creating again",async()=>{const p=api.prepare(scope,preview,{[api.lineKey(preview.lines[0])]:"1"},"2026-01-01","x");api.savePending(p);vi.mocked(api.findShipment).mockResolvedValue(receipt);render(<InvoicePhysicalShipment scope={scope}/>);fireEvent.click(await screen.findByRole("button",{name:"Проверить результат и повторить тот же запрос"}));await screen.findByText("Складское движение подтверждено внутренним актом; бухгалтерские проводки требуют отдельной сверки.");expect(api.createShipment).not.toHaveBeenCalled();});
it("keeps denied recovery pending and does not silently switch scope",async()=>{const p=api.prepare(scope,preview,{[api.lineKey(preview.lines[0])]:"1"},"2026-01-01","x");api.savePending(p);vi.mocked(api.findShipment).mockRejectedValue(new api.ShipmentError("Нет доступа",403));render(<InvoicePhysicalShipment scope={scope}/>);fireEvent.click(await screen.findByRole("button",{name:"Проверить результат и повторить тот же запрос"}));await screen.findByText("Нет доступа");expect(api.loadPending(scope)).toEqual(p);expect(api.createShipment).not.toHaveBeenCalled();});
it("disables shortage rows and treats history error separately",async()=>{vi.mocked(api.previewShipment).mockResolvedValue({...preview,lines:[{...preview.lines[0],free:"-1.00",blocking_reason:"physical_reserves_exceed_stock"}]});vi.mocked(api.shipmentHistory).mockRejectedValue(new Error("Нет связи"));render(<InvoicePhysicalShipment scope={scope}/>);await screen.findByText(/Недостача:/);expect(screen.queryByLabelText("Отгрузить строку 1, склад W")).not.toBeInTheDocument();expect(screen.getByRole("button",{name:"Проверить выбранную отгрузку"})).toBeDisabled();expect(await screen.findByText("История: Нет связи")).toBeInTheDocument();expect(screen.queryByText(/акты WMS для этого счёта не найдены/)).not.toBeInTheDocument();});
it("shows the full structured preview shortage with null amounts in document mode",async()=>{
 vi.mocked(api.previewShipment).mockResolvedValue({...preview,lines:[{...preview.lines[0],execution_mode:"document",stock_issue:stockIssue,blocking_reason:"stock_shortage"}]});
 render(<InvoicePhysicalShipment scope={scope}/>);
 expect(await screen.findByText(/Товар A, склад W; запрошено 1\.00; доступно не определён; дефицит не определён; причина: физический остаток неизвестен\./)).toBeInTheDocument();
 expect(screen.queryByLabelText("Отгрузить строку 1, склад W")).not.toBeInTheDocument();
 expect(screen.getByRole("button",{name:"Проверить выбранную отгрузку"})).toBeDisabled();
});
it("shows structured shortage fields returned when creating a WMS shipment",async()=>{
 vi.mocked(api.previewShipment).mockResolvedValue({...preview,lines:preview.lines.map(line=>({...line,execution_mode:"wms" as const}))});
 vi.mocked(api.createShipment).mockRejectedValue(new api.ShipmentError(api.formatStockIssue(stockIssue),409,"stock_shortage",stockIssue));
 render(<InvoicePhysicalShipment scope={scope}/>);await confirm();
 expect(await screen.findByRole("alert")).toHaveTextContent("Товар A, склад W; запрошено 1.00; доступно не определён; дефицит не определён; причина: физический остаток неизвестен.");
});
it("allows partial shipment from known positive availability and blocks group overshoot",async()=>{
 const issue:api.StockIssue={...stockIssue,reason:"insufficient_stock",message:"Запрошено больше, чем доступно",requested:"3.00",physical:"2.00",reserved:"0.00",reserved_other:"0.00",available:"2.00",shortage:"1.00"};
 const partial:api.Preview={...preview,lines:preview.lines.map(line=>({...line,physical:"2.00",reserved:"0.00",free:"2.00",stock_issue:issue,blocking_reason:"stock_shortage"}))};
 vi.mocked(api.previewShipment).mockResolvedValue(partial);
 render(<InvoicePhysicalShipment scope={scope}/>);
 const first=await screen.findByLabelText("Отгрузить строку 1, склад W"),second=await screen.findByLabelText("Отгрузить строку 2, склад W");
 expect(api.selectableLimit(partial.lines,partial.lines[0])).toBe(200n);
 expect(screen.getAllByText(/Товар A, склад W; запрошено 3\.00; доступно 2\.00/)).toHaveLength(2);
 fireEvent.change(first,{target:{value:"0.50"}});fireEvent.change(second,{target:{value:"0.50"}});
 fireEvent.change(screen.getByLabelText("Основание отгрузки"),{target:{value:"Выдача"}});
 fireEvent.click(screen.getByRole("button",{name:"Проверить выбранную отгрузку"}));
 expect(await screen.findByRole("button",{name:"Подтвердить фактическую отгрузку"})).toBeEnabled();
 expect(()=>api.prepare(scope,partial,{[api.lineKey(partial.lines[0])] : "1.00",[api.lineKey(partial.lines[1])] : "1.01"},"2026-01-01","Выдача")).toThrow(/Суммарная отгрузка/);
});
it("keeps completed rows disabled and paginates history",async()=>{vi.mocked(api.previewShipment).mockResolvedValue({...preview,lines:[{...preview.lines[0],remaining_qty:"0.00",blocking_reason:"fully_shipped"}]});vi.mocked(api.shipmentHistory).mockResolvedValueOnce({items:[receipt],next_after_id:5}).mockResolvedValueOnce({items:[{...receipt,act_id:6}],next_after_id:null});render(<InvoicePhysicalShipment scope={scope}/>);fireEvent.click(await screen.findByRole("button",{name:"Ещё акты"}));await screen.findByLabelText("Внутренний акт 6");expect(api.shipmentHistory).toHaveBeenLastCalledWith(scope,preview.identity,5);expect(screen.getByText("Строка полностью отгружена")).toBeInTheDocument();});
it("ignores a late preview after scope changes",async()=>{let resolve!:(p:api.Preview)=>void;vi.mocked(api.previewShipment).mockImplementationOnce(()=>new Promise(r=>{resolve=r;})).mockRejectedValueOnce(new Error("Другой счёт"));const view=render(<InvoicePhysicalShipment scope={scope}/>);await waitFor(()=>expect(api.previewShipment).toHaveBeenCalledOnce());view.rerender(<InvoicePhysicalShipment scope={{...scope,document_id:12}}/>);await screen.findByText("Другой счёт");await act(async()=>resolve(preview));expect(screen.queryByLabelText("Отгрузить строку 1, склад W")).not.toBeInTheDocument();await waitFor(()=>expect(api.createShipment).not.toHaveBeenCalled());});
it("does not POST if persistence fails",async()=>{render(<InvoicePhysicalShipment scope={scope}/>);await screen.findByLabelText("Отгрузить строку 1, склад W");vi.stubGlobal("sessionStorage",{getItem:()=>null,setItem:()=>{throw new Error("Хранилище недоступно");},removeItem:()=>{}});await confirm();await screen.findByText("Хранилище недоступно");expect(api.createShipment).not.toHaveBeenCalled();});
it("refreshes stale bases only after definite rejection, with a new confirmation",async()=>{vi.mocked(api.createShipment).mockRejectedValue(new api.ShipmentError("Основания изменились",409,"physical_basis_changed"));render(<InvoicePhysicalShipment scope={scope}/>);await confirm();await screen.findByText("Основания изменились");expect(api.loadPending(scope)).toBeNull();expect(screen.queryByRole("button",{name:"Подтвердить фактическую отгрузку"})).not.toBeInTheDocument();fireEvent.click(screen.getByRole("button",{name:"Обновить основания отгрузки"}));await screen.findByLabelText("Отгрузить строку 1, склад W");expect(api.createShipment).toHaveBeenCalledOnce();});
it("does not retry old scope after a late lookup 404",async()=>{api.savePending(api.prepare(scope,preview,{[api.lineKey(preview.lines[0])]:"1"},"2026-01-01","x"));let reject!:(e:unknown)=>void;vi.mocked(api.findShipment).mockImplementation(()=>new Promise((_,r)=>{reject=r;}));const view=render(<InvoicePhysicalShipment scope={scope}/>);fireEvent.click(await screen.findByRole("button",{name:"Проверить результат и повторить тот же запрос"}));view.rerender(<InvoicePhysicalShipment scope={{...scope,document_id:12}}/>);await act(async()=>reject(new api.ShipmentError("missing",404)));expect(api.createShipment).not.toHaveBeenCalled();expect(api.loadPending(scope)).not.toBeNull();});

it("preserves K2 when an unmounted K1 completes after A to B to A recovery",async()=>{
 let finishFirst!:(value:api.Receipt)=>void;
 vi.mocked(api.createShipment).mockImplementationOnce(()=>new Promise(resolve=>{finishFirst=resolve;}));
 const view=render(<InvoicePhysicalShipment scope={scope}/>);await confirm();
 const first=api.loadPending(scope)!;
 view.rerender(<InvoicePhysicalShipment scope={{...scope,document_id:12}}/>);
 view.rerender(<InvoicePhysicalShipment scope={scope}/>);
 vi.mocked(api.findShipment).mockResolvedValue(receipt);
 fireEvent.click(await screen.findByRole("button",{name:"Проверить результат и повторить тот же запрос"}));
 await screen.findByText("Складское движение подтверждено внутренним актом; бухгалтерские проводки требуют отдельной сверки.");
 fireEvent.click(screen.getByRole("button",{name:"Обновить основания отгрузки"}));
 vi.mocked(api.createShipment).mockRejectedValueOnce(new api.ShipmentError("K2 unknown"));
 await confirm();await screen.findByText("K2 unknown");
 const second=api.loadPending(scope)!;
 expect(second.body.source_key).not.toBe(first.body.source_key);
 await act(async()=>finishFirst(receipt));
 expect(api.loadPending(scope)).toEqual(second);
 view.unmount();render(<InvoicePhysicalShipment scope={scope}/>);
 expect(await screen.findByRole("button",{name:"Проверить результат и повторить тот же запрос"})).toBeInTheDocument();
 expect(api.loadPending(scope)).toEqual(second);
});

it("shows released remainder separately from fully shipped and prevents another shipment",async()=>{
 vi.mocked(api.previewShipment).mockResolvedValue({...preview,lines:[{...preview.lines[0],remaining_qty:"0.00",blocking_reason:"remainder_released"}]});
 render(<InvoicePhysicalShipment scope={scope}/>);
 await screen.findByText("Неотгруженный остаток резерва снят");
 expect(screen.queryByText("Строка полностью отгружена")).not.toBeInTheDocument();
 expect(screen.queryByLabelText("Отгрузить строку 1, склад W")).not.toBeInTheDocument();
 expect(screen.getByRole("button",{name:"Проверить выбранную отгрузку"})).toBeDisabled();
 expect(api.createShipment).not.toHaveBeenCalled();
});

it.each([true,false])("resets only validated deterministic shortage refusal %s",async validated=>{
 vi.mocked(api.createShipment).mockRejectedValue(new api.ShipmentError("Нехватка после смены настройки",409,"stock_shortage",validated?stockIssue:undefined));
 render(<InvoicePhysicalShipment scope={scope}/>);await confirm();await screen.findByText("Нехватка после смены настройки");
 if(validated){
  expect(api.loadPending(scope)).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"Обновить основания отгрузки"}));
  expect(await screen.findByLabelText("Отгрузить строку 1, склад W")).toBeInTheDocument();
 }else{
  expect(api.loadPending(scope)).not.toBeNull();
  expect(screen.getByRole("button",{name:"Проверить результат и повторить тот же запрос"})).toBeInTheDocument();
 }
});
