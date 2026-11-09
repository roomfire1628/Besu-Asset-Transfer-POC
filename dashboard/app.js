'use strict';
const $=id=>document.getElementById(id);
const wallets={A:'0x2DA9b3F80534758933944823262dab9cbD75A2D5',B:'0x18eD13257b076457CD64BB9eD135d3848B41709C'};
let csrf='',ticket=null,busy=false,healthy=false,tracked=null;
let latestEvent=null, watchedContext=null, seenEvents=null, flowChecking=false, receiptChecking=false;
const flow=window.TransferFlow;
const short=s=>s.slice(0,8)+'…'+s.slice(-6);
const label=s=>Object.entries(wallets).find(([,v])=>v.toLowerCase()===s.toLowerCase())?.[0]||short(s);
async function api(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'Request failed.');return data;}
function clearReview(){ticket=null;$('review').hidden=true;$('transfer').hidden=false;}
function controls(){ $('reviewButton').disabled=busy||!healthy; $('submit').disabled=busy||!healthy||!ticket; }
async function refresh(){try{const s=await api('/api/state');healthy=true;csrf=s.csrf;$('error').textContent='';$('health').textContent='● RPC healthy · block '+s.block;$('health').className='ok';for(const k of ['A','B']){$('balance'+k).textContent=s.wallets[k].balance+' AST';$('address'+k).textContent=s.wallets[k].address;$('address'+k).title=s.wallets[k].address;}$('supply').textContent=s.supply+' AST';$('contract').textContent='Contract '+s.contract;$('updated').textContent='Updated '+new Date().toLocaleTimeString()+' · refreshes every 5s';$('range').textContent='Latest 30 events · blocks '+s.eventStart+'–'+s.block;observeEvents(s.events);const rows=s.events.map(e=>{const tr=document.createElement('tr');for(const [text,detail] of [[String(e.block),short(e.hash)],[walletLabel(e.from)+' → '+walletLabel(e.to),short(e.from)+' → '+short(e.to)],[e.amount,'']]){const td=document.createElement('td');td.textContent=text;if(detail){const small=document.createElement('small');small.textContent=detail;td.append(small);}tr.append(td);}tr.children[0].title=e.hash;tr.children[1].title=e.from+' → '+e.to;return tr;});$('events').replaceChildren(...rows);if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=3;td.textContent='No Transfer events in this block window.';tr.append(td);$('events').append(tr);}}catch(e){healthy=false;$('health').textContent='● RPC unavailable';$('health').className='bad';$('error').textContent=e.message+' Displayed values may be stale.';}controls();}
$('recipient').value=wallets.B;
$('sender').onchange=()=>{$('recipient').value=wallets[$('sender').value==='A'?'B':'A'];clearReview();};
$('transfer').oninput=clearReview;
$('cancel').onclick=clearReview;
$('refresh').onclick=refresh;
$('transfer').onsubmit=async e=>{e.preventDefault();busy=true;clearReview();controls();$('result').textContent='Reviewing unsigned transfer…';try{const p=await api('/api/preview',{sender:$('sender').value,recipient:$('recipient').value,amount:$('amount').value});ticket=p.ticket;watchedContext={from:p.from,to:p.recipient,amount:p.amount};$('reviewText').textContent=`Send ${p.amount} AST\nFrom: ${p.from}\nTo: ${p.recipient}\nChain: ${p.chainId}\nNonce: ${p.nonce}\nGas limit: ${p.gas}\nGas price: ${p.gasPrice} wei\nMaximum fee: ${p.maxFeeWei} wei\nReview expires in 2 minutes.`;$('review').hidden=false;$('transfer').hidden=true;$('result').textContent='Unsigned review ready.';}catch(e){$('result').textContent=e.message;}finally{busy=false;controls();}};
$('submit').onclick=async()=>{if(!ticket||busy)return;busy=true;controls();const submitted=ticket;clearReview();$('result').textContent='Submitting once…';try{const r=await api('/api/submit',{ticket:submitted});tracked=r.hash;watchedContext={...watchedContext,hash:r.hash};sessionStorage.setItem('besuTransferContext',JSON.stringify(watchedContext));flow.render(document,watchedContext,{status:'pending'},wallets);sessionStorage.setItem('besuLastTransfer',tracked);$('result').textContent=r.message+' '+r.hash;await poll();}catch(e){$('result').textContent=e.message+' Do not retry an uncertain submission; inspect recent events first.';}finally{busy=false;controls();await refresh();}};
function walletLabel(address){const name=label(address);return name==='A'||name==='B'?'Wallet '+name:/^0x0{40}$/i.test(address)?'Token mint':name;}
async function showReceipt(transaction,replay=false){
  const receipt=await api('/api/receipt/'+transaction.hash);
  if(flow.receiptState(receipt)==='confirmed')flow.render(document,transaction,receipt,wallets,replay);
  return receipt;
}
function observeEvents(events){
  latestEvent=events[0]||null;
  $('replay').disabled=!latestEvent||flowChecking||!!tracked;
  if(seenEvents===null){seenEvents=new Set(events.map(e=>e.hash));return;}
  const fresh=events.find(e=>!seenEvents.has(e.hash));
  if(fresh&&!tracked&&!flowChecking){
    flowChecking=true;
    showReceipt(fresh).then(r=>{if(flow.receiptState(r)==='confirmed')events.forEach(e=>seenEvents.add(e.hash));}).catch(()=>{}).finally(()=>{flowChecking=false;$('replay').disabled=!latestEvent||!!tracked;});
  }
}
$('replay').onclick=async()=>{
  if(!latestEvent||flowChecking||!!tracked)return;
  const transaction=latestEvent;
  flowChecking=true;$('replay').disabled=true;
  try{const receipt=await showReceipt(transaction,true);if(flow.receiptState(receipt)!=='confirmed')$('result').textContent='This transfer does not yet have a successful receipt.';}
  catch(e){$('result').textContent='Replay unavailable: receipt could not be verified.';}
  finally{flowChecking=false;$('replay').disabled=!latestEvent||!!tracked;}
};
async function poll(){
  if(!tracked||receiptChecking)return;
  receiptChecking=true;const hash=tracked;
  try{
    const r=await api('/api/receipt/'+hash);
    $('result').textContent='Transaction '+hash+' · '+r.status+(r.block?' · block '+r.block+' · gas '+r.gasUsed:'');
    if(watchedContext)flow.render(document,watchedContext,r,wallets);
    if(flow.receiptState(r)!=='pending'){
      if(seenEvents)seenEvents.add(hash);
      tracked=null;sessionStorage.removeItem('besuLastTransfer');sessionStorage.removeItem('besuTransferContext');
    }
  }catch(e){$('result').textContent='Receipt check unavailable. Transaction '+hash;}
  finally{receiptChecking=false;}
}
try{tracked=sessionStorage.getItem('besuLastTransfer');watchedContext=JSON.parse(sessionStorage.getItem('besuTransferContext')||'null');}catch(e){watchedContext=null;}
refresh();poll();setInterval(()=>{refresh();poll();},5000);
