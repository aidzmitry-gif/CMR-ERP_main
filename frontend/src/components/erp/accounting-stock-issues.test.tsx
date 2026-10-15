import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingStockIssues } from "./accounting-stock-issues";
vi.mock("./invoice-physical-shipment",()=>({InvoicePhysicalShipment:({scope}:{scope:{organization_id:number;document_id:number}})=><p>Операция {scope.organization_id}/{scope.document_id}</p>}));
afterEach(()=>vi.unstubAllGlobals());
const ok=(data:unknown)=>({ok:true,json:async()=>data});
it("requires organization and invoice selection before opening an issue",async()=>{
 const f=vi.fn().mockResolvedValueOnce(ok([{id:1,name:"Организация"}]))
  .mockResolvedValueOnce(ok({organization_id:1,items:[{document_id:3,deal_id:2,number:"17",status:"posted"}],next_after_id:null}));
 vi.stubGlobal("fetch",f);render(<AccountingStockIssues/>);
 await screen.findByRole("option",{name:"Организация"});expect(f).toHaveBeenCalledTimes(1);
 fireEvent.change(screen.getByRole("combobox"),{target:{value:"1"}});
 fireEvent.click(await screen.findByRole("button",{name:"Счёт 17"}));
 expect(screen.getByText("Операция 1/3")).toBeInTheDocument();
});
it("ignores invoices returned after another organization is selected",async()=>{
 let resolve!:(value:unknown)=>void;
 const f=vi.fn().mockResolvedValueOnce(ok([{id:1,name:"Первая"},{id:2,name:"Вторая"}]))
  .mockImplementationOnce(()=>new Promise(r=>{resolve=r;}))
  .mockResolvedValueOnce(ok({organization_id:2,items:[],next_after_id:null}));
 vi.stubGlobal("fetch",f);render(<AccountingStockIssues/>);
 await screen.findByRole("option",{name:"Первая"});
 fireEvent.change(screen.getByRole("combobox"),{target:{value:"1"}});
 fireEvent.change(screen.getByRole("combobox"),{target:{value:"2"}});
 await act(async()=>resolve(ok({organization_id:1,items:[{document_id:3,deal_id:2,number:"Чужая",status:"posted"}],next_after_id:null})));
 expect(screen.queryByRole("button",{name:"Счёт Чужая"})).not.toBeInTheDocument();
});
