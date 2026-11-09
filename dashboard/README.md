# Local Besu asset dashboard

From the existing project:

```sh
cd ~/besu-test-network/asset-transfer-poc
.venv/bin/python -B dashboard/server.py
```

Open http://127.0.0.1:8787 (use this exact address, not `localhost`). Stop with Ctrl+C. Optional: `--port 8788`. Uses existing `web3` and `eth-account` dependencies; no frontend install, compiler, CDN, or build needed.

The RPC endpoint is fixed to http://127.0.0.1:8545, chain 1337. The contract and both wallet addresses are fixed in `server.py`. This does not change Besu configuration or containers.

Balances and supply refresh every five seconds. Activity shows the newest 30 Transfer logs within the latest 5,000 blocks, including mint events; full addresses and transaction hashes are available on hover. RPC failures mark displayed data stale and disable transfer controls.

To transfer: choose Wallet A or B, enter a recipient and exact decimal AST amount, click **Review transfer**, inspect recipient, amount, nonce, and maximum fee, then click **Sign & submit transfer**. Review is unsigned and expires after two minutes. Changed fees or nonce require a new review. Only the explicit submit request loads the appropriate `WALLET_1_PRIVATE_KEY` or `WALLET_2_PRIVATE_KEY` from the existing project `.env`, checks its address, signs, and broadcasts once. Keys and signed bytes never enter HTTP responses, static files, or logs. Keep `.env` owner-readable only and never commit it.

A transaction hash is shown immediately and its receipt is polled until confirmed or reverted. The last hash survives a page reload in this browser tab. Submission uses a one-use review ticket and a server lock to serialize nonces; transport errors are treated as uncertain and never retried automatically. If submission is uncertain, inspect the shown hash or recent events before making another transfer. Tickets and deduplication state are in memory and reset on server restart. No other signer should use these wallets concurrently.

The server binds only to 127.0.0.1. Host validation, exact Origin validation, CSRF tokens, no CORS, restricted static routes, and a same-origin content policy protect browser requests. This is a trusted single-user local tool, not a public or multi-user service; do not reverse-proxy or expose it to a network. Other software running as your user can read the same keys.

Tests (mock signing/RPC; no real transactions):

```sh
cd ~/besu-test-network/asset-transfer-poc/dashboard
../.venv/bin/python -B -m unittest -v test_dashboard.py
node --check app.js
```

Signing follows the Web3.py build/sign/send pattern: https://web3py.readthedocs.io/en/v7.6.0/transactions.html

## Transfer journey

The navy-and-teal dashboard includes a wallet → Besu → recipient diagram. Submitted transfers show a pending state until a receipt is available; successful receipts animate delivery and show the confirmation block and gas used. Reverted receipts show that tokens were not delivered. Newly observed Transfer events also trigger a receipt check before animation. The diagram illustrates wallet settlement, not actual validator traffic.

**Replay latest transfer** verifies the latest event's receipt and replays only the visual. It never signs or submits a transaction. Replays are labeled explicitly. Animation respects the system's reduced-motion preference. The transfer review replaces the entry form and places Cancel separately from Sign & submit.

Additional frontend checks, from the dashboard directory:

```sh
node test_flow.js
node --check app.js
```
