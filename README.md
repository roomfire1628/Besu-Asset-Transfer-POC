# Besu Asset Transfer POC

A local proof of concept for issuing and transferring an ERC-20 token on a private Hyperledger Besu chain. It combines a lean Docker validator, a fixed-supply Solidity contract, Python transaction preparation scripts, and a browser dashboard for balances, activity, and explicitly confirmed transfers.

**Development use only.** This configuration has one validator, local signing keys, and no production availability or Byzantine fault tolerance.

## Architecture

```text
Browser (127.0.0.1:8787)
  └─ Python dashboard: reads state, reviews transfers, signs on explicit submit
       └─ HTTP JSON-RPC (127.0.0.1:8545)
            └─ Besu: one QBFT validator → persistent ./data

Python CLI scripts → same RPC → signed transaction files (no broadcast)
```

| Component | Configuration in this project |
| --- | --- |
| Besu image | `hyperledger/besu:26.11.0` |
| Consensus | QBFT; one genesis validator; target block period 2 seconds |
| QBFT timing | Request timeout 4 seconds; epoch length 30,000 blocks |
| Chain ID | `1337` (JSON-RPC hexadecimal: `0x539`) |
| RPC | Host loopback port 8545; APIs `ETH,NET,WEB3,TXPOOL` |
| Fees | Genesis `zeroBaseFee: true`; Besu minimum gas price 0 |
| Resources | 1 CPU, 768 MiB container memory; JVM heap 128–512 MiB |
| Persistence | `./data:/data`; genesis and node key mounted read-only |

The single validator keeps the demo small. If it stops, block production stops. It provides no redundancy or tolerance of a faulty validator; a production consensus topology requires multiple independently operated validators and additional operational controls. P2P is enabled inside the container on port 30303, but Compose publishes only the loopback RPC port. This is not a multi-node network or a public Ethereum deployment. Zero gas price does not remove gas limits or execution costs measured in gas.

## Prerequisites

- Docker Engine/Desktop running, with Docker Compose v2 (`docker compose`).
- Python 3 with `venv` and `pip`; use the project's existing `.venv` when available.
- Node.js and npm for OpenZeppelin installation and frontend checks. No frontend bundler is required.
- Internet access for initial dependency/image downloads and the Solidity 0.8.20 compiler download on first CLI use.
- A local `keys/nodekey` matching the validator encoded in `genesis.json`, and the appropriate local wallet credentials in `.env`.

**A Git clone alone is not a complete running chain.** Validator keys, wallet secrets, signed transaction files, and blockchain data are intentionally ignored by Git. There is no validator-key provisioning or genesis-generation script in this repository. Restore authorized local configuration securely; an arbitrary replacement node key will not match the genesis validator. The dashboard's existing contract deployment also lives in local chain data, not in the repository.

## Quick start

Run from the repository root (the existing local checkout is shown below):

```sh
cd ~/besu-test-network/asset-transfer-poc
python3 -m venv .venv  # skip if the project environment already exists
.venv/bin/python -m pip install -r requirements.txt
npm ci
```

`requirements.txt` contains `web3` and `py-solc-x`; `eth-account` is supplied through Web3's dependencies. Python dependencies are not pinned. `package-lock.json` locks the npm dependency tree; `package.json` specifies OpenZeppelin Contracts 5.6.1. The CLI scripts select Solidity 0.8.20.

Once the matching local validator key is present:

```sh
docker compose up -d
docker compose ps
docker compose logs --tail=100 besu-validator
```

Check RPC without signing or sending a transaction:

```sh
curl -sS http://127.0.0.1:8545 \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'

curl -sS http://127.0.0.1:8545 \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":2}'
```

Expect chain ID `0x539`. Repeat the block-number request after a few seconds to check that blocks advance. To pause the network while preserving its bind-mounted data:

```sh
docker compose stop
```

Do not delete `data/`, replace `keys/nodekey`, or edit genesis against an existing data directory as a troubleshooting shortcut.

## Existing local chain configuration

These are the public addresses currently hardcoded in the application source. They describe the existing local demo, not guaranteed deployments or balances on a fresh chain.

| Setting | Example from the existing local chain |
| --- | --- |
| Token contract | `0xAC8E7b9f012d519554FaE7897efBAFC0707ef9C3` |
| Wallet A | `0x2DA9b3F80534758933944823262dab9cbD75A2D5` |
| Wallet B | `0x18eD13257b076457CD64BB9eD135d3848B41709C` |
| Chain ID | `1337` |

The dashboard fixes RPC, chain, contract, and wallets in `dashboard/server.py`; wallet addresses also appear in `dashboard/app.js`. The transfer CLI fixes its contract address in `transfer_asset.py`, but reads wallet addresses from `.env`. Deploying again does not automatically update either consumer. Chain ID alone does not identify a particular instance of a local chain.

## Dashboard

```sh
.venv/bin/python -B dashboard/server.py
```

Open **http://127.0.0.1:8787** using that exact host; `localhost` is rejected by the Host check. Stop with Ctrl+C. To use another port:

```sh
.venv/bin/python -B dashboard/server.py --port 8788
```

The dashboard needs neither npm installation nor a Solidity compiler to run; it uses an embedded ABI. It refreshes balances and total supply every five seconds and shows the latest 30 Transfer events within the most recent 5,000 blocks, including mint events. This is a bounded activity view, not a complete explorer.

1. Select Wallet A or B, a nonzero recipient other than the sender, and a positive decimal AST amount with at most 18 decimal places.
2. Select **Review transfer**. This checks the chain, contract, balances, nonce, and estimated fee without loading a signing key or signing.
3. Inspect the amount, addresses, chain, nonce, gas limit, and maximum fee. Select **Sign & submit** to authorize signing and broadcasting. Cancel returns to the form.
4. Watch the transaction hash and receipt state. Confirmation displays the block and gas used; a reverted receipt means the token transfer failed.

Reviews expire after two minutes, and changed transaction details require a new review. The server loads only the selected sender's key from `.env` on submit and verifies its address. A server lock serializes submissions, and one-use tickets deduplicate them within that server process. Do not run another signer against these wallets concurrently.

The browser tab retains the last pending hash across reloads. A transport error can leave submission uncertain: check the hash or recent events before attempting another transfer. There is no automatic resend. Review tickets and submission deduplication reset when the server restarts.

The wallet → Besu → recipient diagram illustrates settlement, not validator traffic. Newly confirmed live transactions animate once; historical activity remains still. Reduced-motion settings are respected. See [dashboard documentation](dashboard/README.md) for more detail.

## Asset deployment and transfer workflow

### Contract

`contracts/AssetToken.sol` inherits OpenZeppelin ERC-20. Its constructor creates **Asset Token (AST)** with **18 decimals**, minting **1,000 AST** to the deploying account. The contract adds no public mint, burn, administrator, pause, or upgrade mechanism; inherited ERC-20 transfers and allowances remain available. Native chain currency pays gas and is separate from AST.

### Local configuration

Keep `.env` private and owner-readable. Configure these names locally without publishing their values:

| Variable | Used by |
| --- | --- |
| `BESU_RPC_URL` | Both CLI scripts; defaults to `http://127.0.0.1:8545` |
| `WALLET_1_ADDRESS` | Deployment and transfer CLI; must match Wallet A's key |
| `WALLET_1_PRIVATE_KEY` | Deployment/transfer CLI and dashboard Wallet A submissions |
| `WALLET_2_ADDRESS` | Transfer CLI |
| `WALLET_2_PRIVATE_KEY` | Transfer CLI validates it; dashboard uses it for Wallet B submissions |

The dashboard ignores `.env` RPC/address settings and uses its fixed source constants. Ensure its signing keys match those fixed wallet addresses. The scripts use a simple `KEY=value` parser, not shell execution; omit `export` prefixes. No credentials are included here.

### Prepare deployment (does not broadcast)

```sh
.venv/bin/python -B deploy_asset_token.py
```

The script checks chain 1337 and Wallet A's key/address, compiles with Solidity 0.8.20, estimates gas with a 20% margin, checks native funds, and signs a constructor transaction. It creates `asset-token.signed-tx.json` with owner-only file permissions and `broadcast: false`. It refuses to overwrite an existing output file.

This command does **not** deploy the contract. There is no CLI broadcast helper in this repository. For a new deployment, separately review and deliberately submit the prepared raw transaction through a trusted local Web3/JSON-RPC workflow, then check a successful receipt and record its `contractAddress`. Do not paste signed bytes into public tools. Update the transfer CLI and dashboard contract constants to the verified deployment before using them. The dashboard cannot deploy contracts.

### Prepare a CLI transfer (does not broadcast)

With the expected contract already deployed and Wallet A holding at least 250 AST:

```sh
.venv/bin/python -B transfer_asset.py
```

This validates both wallet key/address pairs, chain ID, contract bytecode, and token decimals; reads balances and supply; then prepares a fixed **250 AST from Wallet A to Wallet B**. It checks native funds, adds a 20% gas margin, signs with Wallet A, verifies the recovered signer, and creates `transfer-asset.signed-tx.json` with `broadcast: false` and owner-only permissions. It also refuses to overwrite an existing output.

Neither CLI changes balances by itself. For an interactive transfer that actually broadcasts, use the dashboard's review/submit flow instead. Do not later submit a stale CLI transaction after another transaction has consumed the same wallet nonce. A signed transaction is executable authorization even though it does not reveal the private key; keep it private and outside Git.

## Tests

From the repository root:

```sh
(cd dashboard && ../.venv/bin/python -B -m unittest -v test_dashboard.py)
node dashboard/test_flow.js
node --check dashboard/app.js
node --check dashboard/flow.js
```

The Python suite checks exact token amounts, chain/contract guards, unsigned review, one-time signing/submission, uncertain submission handling, changed reviews, and HTTP/static-route protections. It mocks RPC and signing; its HTTP checks bind a temporary loopback port. Frontend checks cover receipt states, direction, one-time animation, deduplication, and reduced motion.

These checks do not send real transactions or prove live consensus, deployment, or contract behavior. There is no dedicated Solidity test suite or end-to-end chain test in the repository.

## Security and operational limits

- Keep `.env`, validator keys, wallet keys, signed transaction files, and chain data out of Git. Ignore rules help prevent accidental inclusion but do not protect files already tracked or secrets previously committed.
- Treat genesis-funded accounts as demo accounts. Use dedicated local keys; never reuse production wallets or place assets of real value on this chain.
- RPC is published only on `127.0.0.1`. Preserve that boundary: the configuration supplies no authenticated public RPC service. Host allowlisting is not authentication.
- The dashboard is a trusted single-user local tool. It binds loopback and checks Host, exact Origin, and CSRF tokens, restricts static routes, and supplies a same-origin content policy. Do not expose it through a proxy or to a network. Software running as your user can access the same key files.
- Single-validator availability, in-memory submission tracking, and unpinned Python dependencies limit reproducibility and reliability. The application is a POC, not an audited custody service.
- Preserve genesis, validator identity, and chain data together. A fresh chain does not inherit the existing token deployment or balances.

## Project tree

```text
.
├── README.md
├── compose.yaml                 # Lean Besu validator
├── genesis.json                 # Chain configuration and genesis allocations
├── contracts/AssetToken.sol     # Fixed initial supply ERC-20
├── deploy_asset_token.py        # Prepare signed deployment only
├── transfer_asset.py            # Prepare signed 250 AST transfer only
├── requirements.txt
├── package.json
├── package-lock.json
├── .gitignore
└── dashboard/
    ├── README.md
    ├── server.py                # Local RPC bridge and explicit signing
    ├── index.html
    ├── app.js
    ├── flow.js
    ├── style.css
    ├── test_dashboard.py
    └── test_flow.js
```

Local-only prerequisites/runtime artifacts include `.env`, `.venv/`, `node_modules/`, `keys/nodekey`, `data/`, and any `*.signed-tx.json` files. They are excluded from the source tree above and should remain untracked.

## Troubleshooting

| Symptom | Check / next step |
| --- | --- |
| RPC unavailable or dashboard values stale | Confirm Docker is running; inspect `docker compose ps` and `docker compose logs --tail=100 besu-validator`; repeat the read-only RPC checks. |
| Blocks do not advance | Check validator logs and that the mounted node key matches the genesis validator. One stopped validator halts this chain. Preserve existing keys/data. |
| Missing key or mount error on startup | `keys/nodekey` must be an actual private-key file provisioned for this genesis, not a directory or arbitrary replacement. |
| Wrong chain ID | CLI expects 1337; dashboard always uses port 8545. Check for another service on that port. Do not change chain data to suppress the guard. |
| Missing contract / no code | The hardcoded address belongs to the existing local deployment. A fresh chain needs a deliberate deployment and consumer configuration update. |
| Dashboard returns 403 | Open `http://127.0.0.1:8787` (or the selected port), not `localhost`; refresh after server restart to obtain a new CSRF token. |
| Port already in use | Inspect the existing service. Use `--port 8788` for the dashboard; changing RPC ports also requires updating fixed dashboard RPC configuration. |
| Missing Python module / Solidity import | Use `.venv/bin/python`; install `requirements.txt` and run `npm ci` at the root. Compiler installation needs network access on first CLI use. |
| Missing `.env`, key mismatch, or insufficient balance | Check local configuration privately. CLI transfer requires both wallet keys; dashboard requires the selected sender's matching key. AST and native gas balances are separate. |
| Prepared file already exists | The CLI intentionally refuses overwrite. Privately review whether it is still pending or could be broadcast; do not blindly delete it and sign again. |
| Review expired or nonce/fee changed | Review again. Avoid concurrent signers and stale prepared transactions. |
| Submission unknown or pending | Inspect the shown transaction hash/receipt and recent activity before any new submission; a transport failure does not prove rejection. |

## License

The Solidity file declares SPDX MIT and imports OpenZeppelin code. No repository-wide `LICENSE` file is currently included; do not infer a license for the entire project from the contract header alone.
