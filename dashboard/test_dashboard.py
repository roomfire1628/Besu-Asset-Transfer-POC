import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import server

class Tests(unittest.TestCase):
    def test_exact_amounts(self):
        self.assertEqual(server.units('250'),250*10**18)
        self.assertEqual(server.units('0.000000000000000001'),1)
        self.assertEqual(server.display(10**18+1),'1.000000000000000001')
        for value in ['0','-1','1e2','NaN','1.0000000000000000001','01',' 1',1,None]:
            with self.assertRaises(ValueError): server.units(value)

    def test_checks(self):
        d=server.Dashboard(); d.w3=Mock(); d.w3.eth.chain_id=1
        with self.assertRaises(ValueError): d.check()
        d.w3.eth.chain_id=1337; d.w3.eth.get_code.return_value=b''
        with self.assertRaises(ValueError): d.check()

    def test_review_does_not_sign(self):
        d=server.Dashboard(); d.check=Mock(); d.w3=Mock(); d.token=Mock()
        d.token.functions.balanceOf.return_value.call.return_value=1000*10**18
        d.token.functions.transfer.return_value.estimate_gas.return_value=50000
        d.w3.eth.gas_price=0; d.w3.eth.get_balance.return_value=0
        d.w3.eth.get_transaction_count.return_value=1
        with patch.object(server.Account,'from_key') as signing:
            review=d.preview({'sender':'A','recipient':server.WALLETS['B'],'amount':'250'})
            self.assertEqual(review['amount'],'250'); signing.assert_not_called()
        d.w3.eth.send_raw_transaction.assert_not_called()

    def test_submit_once_and_ambiguous_send(self):
        for fails in [False,True]:
            d=server.Dashboard(); d.w3=Mock(); d.token=Mock()
            review={'sender':'A','from':server.WALLETS['A'],'recipient':server.WALLETS['B'],'amount':'1','chainId':1337,'gas':60000,'gasPrice':0,'maxFeeWei':'0','nonce':3}
            d.prepare=Mock(return_value=review)
            account=Mock(address=server.WALLETS['A']); account.sign_transaction.return_value=Mock(hash=bytes(32),raw_transaction=b'test')
            if fails: d.w3.eth.send_raw_transaction.side_effect=OSError('private internal error')
            with TemporaryDirectory() as temp:
                Path(temp,'.env').write_text('WALLET_1_PRIVATE_KEY=test-only')
                with patch.object(server,'PROJECT',Path(temp)),patch.object(server.Account,'from_key',return_value=account):
                    ticket=d.preview({})['ticket']
                    result=d.submit({'ticket':ticket})
                    self.assertEqual(result['status'],'unknown' if fails else 'pending')
                    self.assertEqual(d.submit({'ticket':ticket}),result)
                    account.sign_transaction.assert_called_once()
                    d.w3.eth.send_raw_transaction.assert_called_once()
                    with self.assertRaises(ValueError): d.submit({'ticket':'invalid'})

    def test_changed_review_rejected(self):
        d=server.Dashboard(); d.prepare=Mock(side_effect=[{'nonce':1},{'nonce':2}])
        ticket=d.preview({})['ticket']
        with patch.object(server.Account,'from_key') as signing:
            with self.assertRaises(ValueError):d.submit({'ticket':ticket})
            signing.assert_not_called()

    def test_http_guards_and_static(self):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        http.dashboard=server.Dashboard()
        worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
        origin=f'http://127.0.0.1:{http.server_port}'
        try:
            for path in ['/','/app.js','/style.css']:
                with urlopen(origin+path) as r:
                    self.assertEqual(r.status,200)
                    self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
            with self.assertRaises(HTTPError) as error:urlopen(Request(origin+'/.env'))
            self.assertEqual(error.exception.code,404)
            for headers in [{},{'Origin':'https://evil.example','X-CSRF-Token':http.dashboard.csrf},{'Origin':origin,'X-CSRF-Token':'bad'}]:
                with self.assertRaises(HTTPError) as error:urlopen(Request(origin+'/api/submit',data=b'{}',headers=headers))
                self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError) as error:urlopen(Request(origin+'/',headers={'Host':'evil.example'}))
            self.assertEqual(error.exception.code,403)
        finally:http.shutdown();http.server_close();worker.join()

if __name__=='__main__':unittest.main()
