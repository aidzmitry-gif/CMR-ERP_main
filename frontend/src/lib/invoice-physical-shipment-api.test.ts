import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPending, createShipment, findShipment, fingerprint, lineKey, loadPending, parsePreview, prepare, quantity, savePending, shipmentHistory, type Pending, type Preview, type Receipt } from "./invoice-physical-shipment-api";

const scope={organization_id:7,deal_id:3,document_id:11},h="a".repeat(64);
const preview:Preview={identity:{organization_id:7,document_id:11,document_version:2,content_sha256:h},reservation_digest:h,remaining_digest:h,physical_digest:h,lines:[1,2].map(line_no=>({line_no,sku_code:"A",warehouse:"W",original_qty:"3.00",remaining_qty:"3.00",physical:"10.00",reserved:"6.00",free:"4.00",blocking_reason:null}))};
const make=()=>prepare(scope,preview,{[lineKey(preview.lines[0])]:"1",[lineKey(preview.lines[1])]:"2.30"},"2026-01-01","Выдача товара");
const ok=(data:unknown,status=200)=>({ok:status<400,status,json:async()=>data});
async function receipt(p:Pending){const request_hash=await fingerprint({organization_id:7,document_id:11,data:p.body});const snapshot={organization_id:7,document_id:11,document_version:2,content_sha256:h,source_key:p.body.source_key,request_hash,reservation_digest:h,kind:"internal_physical_shipment",operation_date:p.body.operation_date,evidence:p.body.evidence,actor:"picker",before:{},physical:{},lines:p.body.lines.map((l,i)=>({...l,sku_code:"A",source:`address-${i}`,movement_id:i+1,before_id:i+1,after_id:i+3}))};return{act_id:5,source_key:p.body.source_key,request_hash,snapshot,digest:await fingerprint(snapshot)};}
beforeEach(()=>{vi.stubGlobal("crypto",webcrypto);sessionStorage.clear();});
afterEach(()=>vi.unstubAllGlobals());
describe("exact shipment adapter",()=>{
 it("keeps decimal strings and duplicate SKUs as distinct original lines",()=>{expect(make().body.lines.map(l=>l.qty)).toEqual(["1.00","2.30"]);expect(quantity("999999999999.99")).toBe("999999999999.99");});
 it.each(["0","-1","1.001","1e2","NaN","1000000000000"])("rejects invalid quantity %s",v=>expect(()=>quantity(v)).toThrow());
 it("rejects overrun, blocked rows, future date and empty evidence",()=>{expect(()=>prepare(scope,preview,{[lineKey(preview.lines[0])]:"4"},"2026-01-01","x")).toThrow();expect(()=>prepare(scope,preview,{},"2099-01-01","x")).toThrow();expect(()=>prepare(scope,preview,{},"2026-01-01","")).toThrow();const blocked=structuredClone(preview);blocked.lines[0].blocking_reason="physical_reserves_exceed_stock";expect(()=>prepare(scope,blocked,{[lineKey(blocked.lines[0])]:"1"},"2026-01-01","x")).toThrow();});
 it("rejects foreign or malformed previews and duplicate addressed rows",()=>{expect(()=>parsePreview({...preview,identity:{...preview.identity,document_id:12}},preview.identity)).toThrow();expect(()=>parsePreview({...preview,lines:[preview.lines[0],preview.lines[0]]},preview.identity)).toThrow();expect(()=>parsePreview({...preview,lines:[{...preview.lines[0],free:"-1.00"}]},preview.identity)).toThrow();});
 it("persists the same request before create and reuses identical body",async()=>{const p=make();savePending(p);const saved=loadPending(scope)!;expect(saved).toEqual(p);const r=await receipt(p),f=vi.fn().mockResolvedValue(ok(r,201));vi.stubGlobal("fetch",f);await createShipment(saved);await createShipment(saved);expect(f.mock.calls[0][1].body).toBe(f.mock.calls[1][1].body);expect(loadPending({...scope,document_id:99})).toBeNull();});
 it.each(["identity","key","quantity","hash","actor"])("rejects mismatched receipt %s",async change=>{const p=make(),r=await receipt(p);if(change==="identity")r.snapshot.organization_id=8;if(change==="key")r.source_key=crypto.randomUUID();if(change==="quantity")r.snapshot.lines[0].qty="9.00";if(change==="hash")r.digest=h;if(change==="actor")r.snapshot.actor="";vi.stubGlobal("fetch",vi.fn().mockResolvedValue(ok(r)));await expect(createShipment(p)).rejects.toThrow();});
 it("keeps unknown and forbidden responses as errors, 404 does not create",async()=>{const f=vi.fn().mockResolvedValue(ok({detail:"missing"},404));vi.stubGlobal("fetch",f);await expect(findShipment(make())).rejects.toMatchObject({status:404});expect(f).toHaveBeenCalledOnce();f.mockResolvedValue(ok({},403));await expect(createShipment(make())).rejects.toMatchObject({status:403});});
 it("validates history identity, each immutable receipt, cursor and order",async()=>{const r=await receipt(make()),f=vi.fn().mockResolvedValue(ok({identity:preview.identity,items:[r],next_after_id:5}));vi.stubGlobal("fetch",f);expect((await shipmentHistory(scope,preview.identity)).items).toHaveLength(1);f.mockResolvedValue(ok({identity:preview.identity,items:[r,r],next_after_id:null}));await expect(shipmentHistory(scope,preview.identity)).rejects.toThrow();f.mockResolvedValue(ok({identity:{...preview.identity,organization_id:8},items:[],next_after_id:null}));await expect(shipmentHistory(scope,preview.identity)).rejects.toThrow();const bad=structuredClone(r) as Receipt;bad.snapshot.document_id=12;bad.digest=await fingerprint(bad.snapshot);f.mockResolvedValue(ok({identity:preview.identity,items:[bad],next_after_id:null}));await expect(shipmentHistory(scope,preview.identity)).rejects.toThrow();});
});

it("late completion cannot clear a newer request for the same invoice",()=>{
 const first=make(),second=make();
 savePending(first);clearPending(first);savePending(second);
 clearPending(first);expect(loadPending(scope)).toEqual(second);
 clearPending({...second,body:{...second.body,evidence:"different body"}});
 expect(loadPending(scope)).toEqual(second);
 clearPending(second);expect(loadPending(scope)).toBeNull();
});
