import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { InvoiceRemainderRelease } from "./invoice-remainder-release";
import * as api from "@/lib/invoice-remainder-api";
vi.mock("@/lib/invoice-remainder-api", async () => ({ ...await vi.importActual("@/lib/invoice-remainder-api"), prepareRemainder: vi.fn(), submitRemainder: vi.fn() }));
const scope = { organization_id:7,deal_id:3,document_id:11 }, h="a".repeat(64);
const request: api.RemainderRequest = { scope, basis:{ reservation_digest:h,basis_digest:h,remaining:[{source:"invoice:11:1:abc",qty:"4.00",line_no:1,sku_code:"A",warehouse:"W"}],acts:[{id:1,digest:h}] },body:{source_key:"11111111-1111-4111-8111-111111111111",expected_version:1,expected_content_sha256:h,expected_basis_digest:h,evidence:"Отказ от остатка"} };
beforeEach(() => { sessionStorage.clear(); vi.resetAllMocks(); vi.mocked(api.prepareRemainder).mockResolvedValue(request); });
async function prepare() { const input=await screen.findByLabelText("Причина снятия остатка"); await waitFor(()=>expect(input).toBeEnabled()); fireEvent.change(input,{target:{value:"Отказ от остатка"}}); fireEvent.click(screen.getByRole("button",{name:"Рассчитать снятие остатка"})); await screen.findByRole("button",{name:"Подтвердить снятие остатка"}); }
it("persists before submission and recovers identical request after lost reply",async()=>{
 const done=vi.fn(),lock=vi.fn();
 vi.mocked(api.submitRemainder).mockImplementationOnce(async p=>{expect(api.loadRemainder(scope)).toEqual(p);throw new Error("Связь потеряна");}).mockResolvedValueOnce(4);
 const view=render(<InvoiceRemainderRelease scope={scope} disabled={false} onLock={lock} onReleased={done}/>);
 await prepare(); expect(api.submitRemainder).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole("button",{name:"Подтвердить снятие остатка"})); await screen.findByText("Связь потеряна");
 expect(lock).toHaveBeenLastCalledWith(true); view.unmount();
 render(<InvoiceRemainderRelease scope={scope} disabled={false} onLock={lock} onReleased={done}/>);
 fireEvent.click(await screen.findByRole("button",{name:"Проверить результат снятия тем же запросом"}));
 await screen.findByText("Остаток резерва снят. Квитанция № 4.");
 expect(api.submitRemainder).toHaveBeenNthCalledWith(1,request);expect(api.submitRemainder).toHaveBeenNthCalledWith(2,request);expect(api.loadRemainder(scope)).toBeNull();expect(done).toHaveBeenCalledOnce();
});
it("requires a fresh preview after definite stale rejection",async()=>{
 vi.mocked(api.submitRemainder).mockRejectedValue(new api.RemainderError("Изменился резерв","remainder_basis_changed"));
 render(<InvoiceRemainderRelease scope={scope} disabled={false} onLock={vi.fn()} onReleased={vi.fn()}/>);await prepare();
 fireEvent.click(screen.getByRole("button",{name:"Подтвердить снятие остатка"}));await screen.findByText("Изменился резерв");
 expect(api.loadRemainder(scope)).toBeNull();expect(screen.queryByRole("button",{name:"Подтвердить снятие остатка"})).not.toBeInTheDocument();
});
it("does not replace a pending request with a different key",()=>{
 api.saveRemainder(request);expect(()=>api.saveRemainder({...request,body:{...request.body,source_key:"22222222-2222-4222-8222-222222222222"}})).toThrow();
 api.clearRemainder({...request,body:{...request.body,evidence:"changed"}});expect(api.loadRemainder(scope)).toEqual(request);
});
it("does not submit if saving the recovery request fails",async()=>{
 render(<InvoiceRemainderRelease scope={scope} disabled={false} onLock={vi.fn()} onReleased={vi.fn()}/>);await prepare();
 vi.stubGlobal("sessionStorage", {getItem:()=>null,setItem:()=>{throw new Error("Storage unavailable");}});
 try { fireEvent.click(screen.getByRole("button",{name:"Подтвердить снятие остатка"}));await screen.findByText("Storage unavailable");expect(api.submitRemainder).not.toHaveBeenCalled(); }
 finally { vi.unstubAllGlobals(); }
});
