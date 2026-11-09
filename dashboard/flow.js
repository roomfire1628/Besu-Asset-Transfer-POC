'use strict';
(function(root){
  function receiptState(receipt){
    if(receipt.status==='confirmed' && Number.isInteger(receipt.block) && receipt.block>=0)return 'confirmed';
    if(receipt.status==='reverted')return 'reverted';
    return 'pending';
  }
  function endpoint(address,wallets){
    const entry=Object.entries(wallets).find(([,v])=>v.toLowerCase()===address.toLowerCase());
    if(entry)return {title:'Wallet '+entry[0],icon:entry[0],detail:address.slice(0,6)+'…'+address.slice(-4)};
    if(/^0x0{40}$/i.test(address))return {title:'Token mint',icon:'+',detail:'Zero address'};
    return {title:'Address',icon:'↗',detail:address.slice(0,6)+'…'+address.slice(-4)};
  }
  function render(doc,transaction,receipt,wallets,replay=false){
    const el=id=>doc.getElementById(id), status=receiptState(receipt);
    const from=endpoint(transaction.from,wallets),to=endpoint(transaction.to,wallets);
    el('flowFrom').textContent=from.title;el('sourceIcon').textContent=from.icon;el('flowFromDetail').textContent=from.detail;
    el('flowTo').textContent=to.title;el('destinationIcon').textContent=to.icon;el('flowToDetail').textContent=to.detail;
    el('flow').classList.remove('animate');
    el('flow').dataset.status=status;
    if(status==='confirmed'){
      void el('flow').offsetWidth;
      el('flow').classList.add('animate');
    }
    el('flowLeft').textContent='Submitted';
    el('flowRight').textContent=status==='confirmed'?'Delivered':status==='reverted'?'Reverted':'Awaiting receipt';
    el('flowNetwork').textContent=status==='confirmed'?'Block '+receipt.block:'Chain 1337';
    el('flowStatus').textContent=(replay?'Replay · ':'')+(status==='confirmed'?transaction.amount+' AST confirmed':status==='reverted'?'Transaction reverted · tokens not delivered':'Transfer pending · awaiting confirmation');
    el('flowMeta').textContent=status==='confirmed'?'Block '+receipt.block+' · gas '+receipt.gasUsed:status==='reverted'?'Receipt status 0':'Receipt-based confirmation';
    el('flowStatus').title=transaction.hash||'';
  }
  const api={receiptState,endpoint,render};
  if(typeof module!=='undefined')module.exports=api;
  else root.TransferFlow=api;
})(typeof window!=='undefined'?window:this);
