#!/usr/bin/env python3
"""Local Besu dashboard. No signing occurs before an explicit confirmed POST."""
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from web3 import Web3
from eth_account import Account

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
RPC = 'http://127.0.0.1:8545'
CHAIN = 1337
CONTRACT = Web3.to_checksum_address('0xAC8E7b9f012d519554FaE7897efBAFC0707ef9C3')
WALLETS = {'A': Web3.to_checksum_address('0x2DA9b3F80534758933944823262dab9cbD75A2D5'), 'B': Web3.to_checksum_address('0x18eD13257b076457CD64BB9eD135d3848B41709C')}
ABI = [{'type':'function','name':name,'stateMutability':'view','inputs':inputs,'outputs':[{'name':'','type':out}]} for name,inputs,out in [('balanceOf',[{'name':'account','type':'address'}],'uint256'),('totalSupply',[],'uint256'),('decimals',[],'uint8')]] + [{'type':'function','name':'transfer','stateMutability':'nonpayable','inputs':[{'name':'to','type':'address'},{'name':'amount','type':'uint256'}],'outputs':[{'name':'','type':'bool'}]}, {'type':'event','name':'Transfer','anonymous':False,'inputs':[{'name':'from','type':'address','indexed':True},{'name':'to','type':'address','indexed':True},{'name':'value','type':'uint256','indexed':False}]}]

def units(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]{0,59})(\.[0-9]{1,18})?', value):
        raise ValueError('Enter a positive decimal amount with at most 18 decimal places.')
    whole, _, fraction = value.partition('.')
    amount = int(whole)*10**18 + int(fraction.ljust(18,'0'))
    if not 0 < amount < 2**256:
        raise ValueError('Amount is outside the token range.')
    return amount

def display(value):
    whole, fraction = divmod(value,10**18)
    return str(whole) + ('.'+str(fraction).zfill(18).rstrip('0') if fraction else '')

class Dashboard:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={'timeout':5}))
        self.token = self.w3.eth.contract(address=CONTRACT,abi=ABI)
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.previews = {}
        self.results = {}

    def check(self):
        if self.w3.eth.chain_id != CHAIN:
            raise ValueError('RPC chain ID is not 1337; transfers disabled.')
        if not self.w3.eth.get_code(CONTRACT):
            raise ValueError('AssetToken contract is missing; transfers disabled.')
        if self.token.functions.decimals().call() != 18:
            raise ValueError('Unexpected token decimals; transfers disabled.')

    def state(self):
        self.check()
        block = self.w3.eth.block_number
        start = max(0,block-4999)
        logs = self.token.events.Transfer().get_logs(from_block=start,to_block=block)
        events = [{'from':e['args']['from'],'to':e['args']['to'],'amount':display(e['args']['value']),'hash':Web3.to_hex(e['transactionHash']),'block':e['blockNumber']} for e in sorted(logs,key=lambda e:(e['blockNumber'],e['logIndex']),reverse=True)[:30]]
        return {'healthy':True,'block':block,'chainId':CHAIN,'contract':CONTRACT,'rpc':RPC,'wallets':{k:{'address':v,'balance':display(self.token.functions.balanceOf(v).call(block_identifier=block))} for k,v in WALLETS.items()},'supply':display(self.token.functions.totalSupply().call(block_identifier=block)),'events':events,'eventStart':start,'csrf':self.csrf}

    def prepare(self, data):
        self.check()
        sender = data.get('sender')
        if sender not in WALLETS:
            raise ValueError('Choose Wallet A or B.')
        recipient = data.get('recipient','')
        if not Web3.is_address(recipient) or int(recipient,16)==0:
            raise ValueError('Enter a valid nonzero recipient address.')
        recipient = Web3.to_checksum_address(recipient)
        if recipient == WALLETS[sender]:
            raise ValueError('Choose a recipient different from the sender.')
        amount = units(data.get('amount'))
        if self.token.functions.balanceOf(WALLETS[sender]).call() < amount:
            raise ValueError('Insufficient AST balance.')
        call = self.token.functions.transfer(recipient,amount)
        gas = (call.estimate_gas({'from':WALLETS[sender]})*120+99)//100
        price = self.w3.eth.gas_price
        if self.w3.eth.get_balance(WALLETS[sender]) < gas*price:
            raise ValueError('Insufficient native balance for gas.')
        return {'sender':sender,'from':WALLETS[sender],'recipient':recipient,'amount':display(amount),'gas':gas,'gasPrice':price,'maxFeeWei':str(gas*price),'nonce':self.w3.eth.get_transaction_count(WALLETS[sender],'pending'),'chainId':CHAIN}

    def preview(self,data):
        with self.lock:
            review = self.prepare(data)
            now=time.monotonic()
            self.previews={k:v for k,v in self.previews.items() if v[0]>now}
            if len(self.previews)>=100:
                raise ValueError('Too many outstanding reviews; wait two minutes.')
            ticket=secrets.token_urlsafe(32)
            self.previews[ticket]=(now+120,review)
            return {**review,'ticket':ticket}

    def submit(self,data):
        ticket=data.get('ticket','')
        with self.lock:
            if ticket in self.results:
                return self.results[ticket]
            item=self.previews.pop(ticket,None)
            if not item or item[0]<time.monotonic():
                raise ValueError('Review expired or already used. Review the transfer again.')
            review=item[1]
            current=self.prepare(review)
            if current != review:
                raise ValueError('Balance, nonce or fees changed. Review the transfer again.')
            # Read secrets only after the user's explicit submit action. Never log them.
            env={}
            for line in (PROJECT/'.env').read_text().splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k,v=line.split('=',1); env[k.strip()]=v.strip().strip('\"\'')
            key=env.get('WALLET_1_PRIVATE_KEY' if review['sender']=='A' else 'WALLET_2_PRIVATE_KEY')
            try:
                account=Account.from_key(key)
            except Exception:
                raise ValueError('Sender signing key is unavailable or invalid.') from None
            if account.address != review['from']:
                raise ValueError('Sender key does not match the expected wallet.')
            tx=self.token.functions.transfer(review['recipient'],units(review['amount'])).build_transaction({'from':review['from'],'chainId':CHAIN,'nonce':review['nonce'],'gas':review['gas'],'gasPrice':review['gasPrice']})
            signed=account.sign_transaction(tx)
            txhash=Web3.to_hex(signed.hash)
            # Record before network send: ambiguous transport failures must never trigger a resend.
            result={'hash':txhash,'status':'unknown','message':'Submission outcome unknown. Check this hash; do not resubmit.'}
            self.results[ticket]=result
            try:
                self.w3.eth.send_raw_transaction(signed.raw_transaction)
                result.update(status='pending',message='Submitted. Waiting for a receipt.')
            except Exception:
                pass
            return result

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def reply(self,status,body,kind='application/json'):
        raw=json.dumps(body).encode() if kind=='application/json' else body
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",'Referrer-Policy':'no-referrer','Connection':'close'}.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)

    def allowed(self):
        return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.allowed(): return self.reply(403,{'error':'Use the printed localhost URL.'})
        try:
            if self.path in ('/','/app.js','/flow.js','/style.css'):
                name={'/':'index.html','/app.js':'app.js','/flow.js':'flow.js','/style.css':'style.css'}[self.path]
                kind={'/':'text/html; charset=utf-8','/app.js':'text/javascript','/flow.js':'text/javascript','/style.css':'text/css'}[self.path]
                return self.reply(200,(ROOT/name).read_bytes(),kind)
            if self.path=='/api/state': return self.reply(200,self.server.dashboard.state())
            if re.fullmatch(r'/api/receipt/0x[0-9a-fA-F]{64}',self.path):
                from web3.exceptions import TransactionNotFound
                try:
                    r=self.server.dashboard.w3.eth.get_transaction_receipt(self.path.rsplit('/',1)[1])
                    return self.reply(200,{'status':'confirmed' if r['status']==1 else 'reverted','block':r['blockNumber'],'gasUsed':r['gasUsed']})
                except TransactionNotFound:
                    return self.reply(200,{'status':'pending'})
            self.reply(404,{'error':'Not found.'})
        except ValueError as e: self.reply(503,{'error':str(e),'healthy':False})
        except Exception: self.reply(503,{'error':'RPC unavailable or read failed. Check Besu and refresh.','healthy':False})

    def do_POST(self):
        origin=f'http://127.0.0.1:{self.server.server_port}'
        if not self.allowed() or self.headers.get('Origin')!=origin or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),self.server.dashboard.csrf):
            return self.reply(403,{'error':'Request rejected.'})
        try:
            if self.headers.get('Content-Type')!='application/json': raise ValueError('JSON required.')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=4096: raise ValueError('Invalid request size.')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict): raise ValueError('JSON object required.')
            if self.path=='/api/preview': result=self.server.dashboard.preview(data)
            elif self.path=='/api/submit': result=self.server.dashboard.submit(data)
            else: return self.reply(404,{'error':'Not found.'})
            self.reply(200,result)
        except ValueError as e: self.reply(400,{'error':str(e)})
        except Exception: self.reply(503,{'error':'Operation failed. Check RPC or local configuration; no automatic retry.'})


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8787)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.dashboard=Dashboard()
    print(f'Besu dashboard: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
