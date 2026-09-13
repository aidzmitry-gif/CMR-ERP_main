"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { InvoiceRemainderRelease } from "./invoice-remainder-release";
import { AccountingSourceLink } from "./accounting-source-link";
import { clearPending, createShipment, findShipment, lineKey, loadPending, prepare, previewShipment, savePending, ShipmentError, shipmentHistory, shipmentIdentity, today,
  type Identity, type Pending, type Preview, type Receipt, type Scope } from "@/lib/invoice-physical-shipment-api";

const message=(e:unknown)=>e instanceof Error?e.message:"Не удалось выполнить действие.";
const blockers={remainder_released:"Неотгруженный остаток резерва снят",fully_shipped:"Строка полностью отгружена",physical_stock_unknown:"Физический остаток требует сверки",physical_reserves_exceed_stock:"Недостача: резервы превышают физический остаток"};
function Act({receipt,org}:{receipt:Receipt;org:number}){
  return <article className="space-y-2 rounded-lg border border-line p-3" aria-label={`Внутренний акт ${receipt.act_id}`}><h3 className="font-semibold">Внутренний акт №{receipt.act_id} · {receipt.snapshot.operation_date}</h3><p>Автор: {receipt.snapshot.actor}</p><p>{receipt.snapshot.evidence}</p><ul>{receipt.snapshot.lines.map(l=><li key={lineKey(l)}>Строка {l.line_no} · {l.sku_code} · {l.warehouse} · {l.qty}</li>)}</ul><AccountingSourceLink org={String(org)} source={`wms:physical-shipment:${org}:${receipt.source_key}`} /></article>;
}
export function InvoicePhysicalShipment({scope}:{scope:Scope}){
  return <Panel key={`${scope.organization_id}:${scope.deal_id}:${scope.document_id}`} scope={scope}/>;
}
function Panel({scope}:{scope:Scope}){
  const [remainderLocked,setRemainderLocked]=useState(true);
  const [preview,setPreview]=useState<Preview|null>(null),[values,setValues]=useState<Record<string,string>>({});
  const [date,setDate]=useState(today),[evidence,setEvidence]=useState("");
  const [pending,setPending]=useState<Pending|null>(null),[review,setReview]=useState<Pending|null>(null),[receipt,setReceipt]=useState<Receipt|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[loading,setLoading]=useState(true),[storageError,setStorageError]=useState(false);
  const [identity,setIdentity]=useState<Identity|null>(null),[history,setHistory]=useState<Receipt[]>([]),[historyNext,setHistoryNext]=useState<number|null>(null),[historyError,setHistoryError]=useState(""),[historyBusy,setHistoryBusy]=useState(false),[historyLoaded,setHistoryLoaded]=useState(false);
  const alive=useRef(true),lock=useRef(false),historyLock=useRef(false),historyRequest=useRef(0);
  useEffect(()=>{alive.current=true;let active=true;
    void Promise.resolve().then(async()=>{if(!active)return;try{const saved=loadPending(scope);setPending(saved);if(saved)setLoading(false);else {const p=await previewShipment(scope);if(active)setPreview(p);}}catch(e){if(active){setError(message(e));try{loadPending(scope);}catch{setStorageError(true);setError("Сохранённый запрос недоступен или повреждён. Новая отправка заблокирована до восстановления операции.");}}}finally{if(active)setLoading(false);}});
    const ticket=++historyRequest.current;
    void shipmentIdentity(scope).then(async i=>{const h=await shipmentHistory(scope,i);if(active&&ticket===historyRequest.current){setIdentity(i);setHistory(h.items);setHistoryNext(h.next_after_id);setHistoryLoaded(true);}}).catch(e=>{if(active&&ticket===historyRequest.current)setHistoryError(message(e));});
    return ()=>{active=false;alive.current=false;};
  // The keyed panel binds all async work and saved operations to one exact scope.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);
  async function reload(){if(lock.current)return;lock.current=true;setBusy(true);setError("");try{const p=await previewShipment(scope);if(alive.current){setPreview(p);setReview(null);setValues({});setReceipt(null);}}catch(e){if(alive.current)setError(message(e));}finally{lock.current=false;if(alive.current)setBusy(false);}}
  async function historyPage(more=false){if(historyLock.current)return;historyLock.current=true;const ticket=++historyRequest.current;setHistoryBusy(true);setHistoryError("");try{const i=identity??await shipmentIdentity(scope);const page=await shipmentHistory(scope,i,more?(historyNext??0):0);if(alive.current&&ticket===historyRequest.current){setIdentity(i);setHistory(h=>more?[...h,...page.items]:page.items);setHistoryNext(page.next_after_id);setHistoryLoaded(true);}}catch(e){if(alive.current&&ticket===historyRequest.current)setHistoryError(message(e));}finally{historyLock.current=false;if(alive.current)setHistoryBusy(false);}}
  function reviewRequest(){if(!preview)return;setError("");try{setReview(prepare(scope,preview,values,date,evidence));}catch(e){setError(message(e));}}
  async function submit(p:Pending,recover=false){
    if(lock.current)return;lock.current=true;setBusy(true);setError("");
    try{
      // Persistence must succeed before any possible create request.
      savePending(p);setPending(p);setReview(null);
      let result:Receipt;
      if(recover){try{result=await findShipment(p);}catch(e){if(!(e instanceof ShipmentError)||e.status!==404)throw e;if(!alive.current)return;result=await createShipment(p);}}
      else result=await createShipment(p);
      if(alive.current){setReceipt(result);setPending(null);setPreview(null);}
      clearPending(p);
      if(alive.current)void historyPage();
    }catch(e){
      if(alive.current){setError(message(e));
        // A deterministic stale-basis rejection cannot be a successful same-key replay.
        if(e instanceof ShipmentError&&e.status===409&&["physical_basis_changed","remaining_basis_changed"].includes(e.code??"")){
          try{clearPending(p);setPending(null);setPreview(null);setReview(null);}catch{setStorageError(true);}
        }
      }
    }finally{lock.current=false;if(alive.current)setBusy(false);}
  }
  return <section aria-label="Фактическая отгрузка счёта" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <header><h2 className="font-semibold">Фактическая отгрузка · счёт ID {scope.document_id}</h2><p className="text-sm text-muted">Юрлицо ID {scope.organization_id}. Внутренний складской акт. Не является ТН/ТТН.</p></header>
    {loading&&<p role="status">Проверка исходного счёта и остатков…</p>}
    {error&&<p role="alert">{error}</p>}
    {pending&&<div className="space-y-2 rounded border border-amber-300 p-3"><p role="status">Запрос сохранён. До проверки результата не создавайте новую отгрузку. Повтор использует прежние строки, дату и количества.</p><p>Дата {pending.body.operation_date} · {pending.body.evidence}</p><ul>{pending.body.lines.map(l=><li key={lineKey(l)}>Строка {l.line_no} · {l.warehouse} · {l.qty}</li>)}</ul><Button disabled={busy||remainderLocked||storageError} onClick={()=>void submit(pending,true)}>Проверить результат и повторить тот же запрос</Button></div>}
    {!loading&&!pending&&!storageError&&!review&&<Button variant="secondary" disabled={busy||remainderLocked} onClick={()=>void reload()}>Обновить основания отгрузки</Button>}
    {preview&&!pending&&!storageError&&!review&&<div className="space-y-3">
      <p className="text-sm">Версия счёта {preview.identity.document_version}. Введите количество только в отгружаемых строках. Склады соответствуют исходному резерву.</p>
      <fieldset disabled={busy||remainderLocked} className="space-y-3"><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Строка / товар</th><th>Склад</th><th>Исходно / осталось</th><th>Физически / резерв / свободно</th><th>Отгрузить</th></tr></thead><tbody>{preview.lines.map(l=><tr key={lineKey(l)} className="border-t border-line"><td className="py-3">{l.line_no} · {l.sku_code}</td><td>{l.warehouse}</td><td>{l.original_qty} / {l.remaining_qty}</td><td>{l.physical??"Неизвестно"} / {l.reserved??"Неизвестно"} / {l.free??"Неизвестно"}</td><td>{l.blocking_reason?<span>{blockers[l.blocking_reason]}</span>:<input className="w-28 rounded border border-line p-2" aria-label={`Отгрузить строку ${l.line_no}, склад ${l.warehouse}`} inputMode="decimal" value={values[lineKey(l)]??""} onChange={e=>setValues(v=>({...v,[lineKey(l)]:e.target.value}))}/>}</td></tr>)}</tbody></table></div>
      <label className="block">Дата фактической отгрузки <input className="rounded border border-line p-2" type="date" max={today()} value={date} onChange={e=>setDate(e.target.value)}/></label>
      <label className="block">Основание отгрузки <textarea className="block w-full rounded border border-line p-2" maxLength={1000} value={evidence} onChange={e=>setEvidence(e.target.value)}/></label>
      <Button onClick={reviewRequest} disabled={!preview.lines.some(l=>!l.blocking_reason)}>Проверить выбранную отгрузку</Button></fieldset>
    </div>}
    {review&&!pending&&<div className="space-y-3 rounded border border-accent p-3"><h3 className="font-semibold">Подтверждение фактического выбытия</h3><p>{review.body.operation_date} · {review.body.evidence}</p><ul>{review.body.lines.map(l=><li key={lineKey(l)}>Строка {l.line_no} · {review.skus.find(s=>lineKey(s)===lineKey(l))?.sku_code} · {l.warehouse} · {l.qty}</li>)}</ul><p>После подтверждения будут записаны расход товара и уменьшение резерва.</p><Button disabled={busy||remainderLocked} onClick={()=>void submit(review)}>Подтвердить фактическую отгрузку</Button><Button variant="secondary" disabled={busy||remainderLocked} onClick={()=>setReview(null)}>Вернуться к количествам</Button></div>}
    {receipt&&<div role="status"><p>Фактическая отгрузка подтверждена.</p><Act receipt={receipt} org={scope.organization_id}/></div>}
    <InvoiceRemainderRelease scope={scope} disabled={busy||loading||!!pending||!!review||storageError} onLock={setRemainderLocked} onReleased={()=>{void reload();void historyPage();}} />
    <section aria-label="История внутренних актов" className="space-y-3 border-t border-line pt-4"><h3 className="font-semibold">История внутренних актов</h3><p className="text-sm text-muted">Только акты этого счёта в WMS. Это не полный реестр ТН/ТТН и внешних отгрузок.</p>{historyError&&<p role="alert">История: {historyError}</p>}{!historyLoaded&&!historyError&&<p>Загрузка истории…</p>}{historyLoaded&&!historyError&&!history.length&&<p>Внутренние акты WMS для этого счёта не найдены.</p>}{history.map(r=><Act key={r.act_id} receipt={r} org={scope.organization_id}/>)}<Button variant="secondary" disabled={historyBusy} onClick={()=>void historyPage()}>Обновить историю</Button>{historyNext!==null&&<Button disabled={historyBusy} onClick={()=>void historyPage(true)}>Ещё акты</Button>}</section>
  </section>;
}
