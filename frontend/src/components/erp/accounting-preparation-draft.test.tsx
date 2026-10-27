import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingPreparationDraft } from "./accounting-preparation-draft";

const sourceKey="00000000-0000-4000-8000-000000000001", source=`wms:physical-shipment:1:${sourceKey}`;
const props={org:"1",source,sourceKey,payload:{form:{explanation:"Partial"}},disabled:false,onRestore:vi.fn(),onBusy:vi.fn()};
const saved={revision:1,draft:{organization_id:1,source,revision:1,payload:props.payload,actor:"Бухгалтер",created_at:"2026-09-10"}};
const reply=(value:unknown)=>({ok:true,json:async()=>value});
afterEach(()=>{vi.unstubAllGlobals();vi.clearAllMocks();});

it("requires loading and explicit adoption of an existing revision",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(reply(saved)));
  render(<AccountingPreparationDraft {...props}/>);
  expect(screen.getByText("Сохранить подготовку")).toBeDisabled();
  fireEvent.click(screen.getByText("Проверить сохранённый черновик"));
  await screen.findByText("Восстановить сохранённые поля");
  expect(screen.getByText("Сохранить подготовку")).toBeDisabled();
  expect(props.onRestore).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Восстановить сохранённые поля"));
  expect(props.onRestore).toHaveBeenCalledWith(props.payload);
  expect(screen.getByText("Сохранить подготовку")).not.toBeDisabled();
});

it("retries an uncertain save with the exact same command key",async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(reply({revision:0,draft:null})).mockRejectedValueOnce(new Error("network"))
    .mockImplementationOnce((_url,options) => Promise.resolve(reply({...saved,draft:{...saved.draft,request_key:JSON.parse(options.body).request_key}}))); vi.stubGlobal("fetch",fetcher);
  render(<AccountingPreparationDraft {...props}/>);
  fireEvent.click(screen.getByText("Проверить сохранённый черновик"));
  await screen.findByText("Сохранённого черновика нет.");
  fireEvent.click(screen.getByText("Сохранить подготовку"));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByText("Сохранить подготовку"));
  await screen.findByText("Черновик версии 1 сохранён.");
  expect(fetcher.mock.calls[1][1].body).toBe(fetcher.mock.calls[2][1].body);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({expected_revision:0,payload:props.payload});
});

it("requires reload on conflict without overwriting the visible form",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(reply({revision:0,draft:null})).mockResolvedValueOnce({ok:false,status:409}));
  render(<AccountingPreparationDraft {...props}/>);
  fireEvent.click(screen.getByText("Проверить сохранённый черновик"));
  await screen.findByText("Сохранённого черновика нет.");
  fireEvent.click(screen.getByText("Сохранить подготовку"));
  await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("Черновик изменён"));
  expect(screen.getByText("Сохранить подготовку")).toBeDisabled();
  expect(props.onRestore).not.toHaveBeenCalled();
});

it("does not adopt a draft when restoration rejects its contents",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(reply(saved)));
  render(<AccountingPreparationDraft {...props} onRestore={()=>{throw new Error("Другой акт");}}/>);
  fireEvent.click(screen.getByText("Проверить сохранённый черновик"));
  await screen.findByText("Восстановить сохранённые поля");
  fireEvent.click(screen.getByText("Восстановить сохранённые поля"));
  expect(screen.getByRole("alert")).toHaveTextContent("Другой акт");
  expect(screen.getByText("Сохранить подготовку")).toBeDisabled();
});


it.each(["empty", "wrong_version", "wrong_command"])("does not claim success for a mismatched save receipt: %s",async caseName=>{
  const fetcher=vi.fn().mockResolvedValueOnce(reply({revision:0,draft:null})).mockImplementationOnce((_url,options)=> {
    const key=JSON.parse(options.body).request_key;
    return Promise.resolve(reply(caseName === "empty" ? {revision:0,draft:null} : {revision:caseName === "wrong_version" ? 2 : 1,draft:{...saved.draft,revision:caseName === "wrong_version" ? 2 : 1,request_key:caseName === "wrong_command" ? "other" : key}}));
  });
  vi.stubGlobal("fetch",fetcher);
  render(<AccountingPreparationDraft {...props}/>);
  fireEvent.click(screen.getByText("Проверить сохранённый черновик"));
  await screen.findByText("Сохранённого черновика нет.");
  fireEvent.click(screen.getByText("Сохранить подготовку"));
  expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждает сохранение");
  expect(screen.queryByText(/Черновик версии .* сохранён/)).not.toBeInTheDocument();
});
