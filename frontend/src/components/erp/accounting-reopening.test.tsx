import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingReopening } from "./accounting-reopening";
afterEach(() => vi.unstubAllGlobals());
const plan = { organization_id: 1, from_month: "2026-10", status: "preview", posted: false, basis_digest: "a".repeat(64), periods: [{month:"2026-10",closed:true,generation:3}], reversals: [] };
const props = { org: "1", month: "2026-10", onLock: vi.fn(), onReopened: vi.fn() };
it.each([null, [], [{ month: "2026-10", closed: true, generation: -1 }]])("rejects malformed periods %j", async periods => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok:true,json:async()=>({...plan,periods})}));
  render(<AccountingReopening {...props}/>);
  fireEvent.click(screen.getByText("Просмотреть последствия открытия"));
  expect(await screen.findByRole("alert")).toHaveTextContent("неполный расчёт");
  expect(screen.queryByText("Подтвердить открытие периодов")).toBeNull();
});
it("retains the exact request after lost response and unlocks only after verified result", async () => {
  const bodies: string[]=[];
  vi.stubGlobal("fetch",vi.fn(async (_url:string,options?:RequestInit)=>{
    if(options?.method!=="POST")return {ok:true,json:async()=>plan};
    bodies.push(String(options.body));
    if(bodies.length===1)throw new Error("lost");
    return {ok:true,json:async()=>({organization_id:1,from_month:"2026-10",request_key:JSON.parse(bodies[0]).request_key,receipt_id:1,digest:"b".repeat(64),periods:[{month:"2026-10",closed:false}],current_periods:[{month:"2026-10",closed:false}]})};
  }));
  render(<AccountingReopening {...props}/>);
  fireEvent.change(screen.getByLabelText("Причина открытия"),{target:{value:"Проверенная корректировка"}});
  fireEvent.click(screen.getByText("Просмотреть последствия открытия"));
  fireEvent.click(await screen.findByText("Подтвердить открытие периодов"));
  const retry=await screen.findByText("Проверить результат открытия");
  expect(screen.getByLabelText("Причина открытия")).toBeDisabled();
  fireEvent.click(retry);
  expect(await screen.findByRole("status")).toHaveTextContent("Периоды открыты");
  expect(bodies[0]).toBe(bodies[1]);
});
