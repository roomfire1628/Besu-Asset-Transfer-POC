#!/usr/bin/env python3
"""Compile AssetToken and prepare a signed deployment transaction without broadcasting."""

import json
import os
import sys
from pathlib import Path

from solcx import compile_files, get_installed_solc_versions, install_solc, set_solc_version
from web3 import Web3
from eth_account import Account

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
CONTRACT_FILE = ROOT / "contracts" / "AssetToken.sol"
OUTPUT_FILE = ROOT / "asset-token.signed-tx.json"
CHAIN_ID = 1337
SOLC_VERSION = "0.8.20"
OPENZEPPELIN_IMPORT = str(ROOT / "node_modules")


def load_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def compile_contract():
    if SOLC_VERSION not in {str(v) for v in get_installed_solc_versions()}:
        print(f"Installing Solidity compiler {SOLC_VERSION}...")
        install_solc(SOLC_VERSION)
    set_solc_version(SOLC_VERSION)
    result = compile_files(
        [str(CONTRACT_FILE)],
        output_values=["abi", "bin"],
        import_remappings=[f"@openzeppelin/={OPENZEPPELIN_IMPORT}/@openzeppelin/"],
        solc_version=SOLC_VERSION,
    )
    contract = next(
        (value for key, value in result.items() if key.endswith(":AssetToken")),
        None,
    )
    if not contract or not contract.get("bin"):
        raise RuntimeError("AssetToken compilation did not produce deployment bytecode")
    return contract


def main():
    if OUTPUT_FILE.exists():
        raise SystemExit(f"Refusing to overwrite existing signed transaction file: {OUTPUT_FILE.name}")
    if not ENV_FILE.is_file():
        raise SystemExit("Missing .env file")

    env = load_env(ENV_FILE)
    rpc_url = env.get("BESU_RPC_URL", "http://127.0.0.1:8545")
    private_key = env.get("WALLET_1_PRIVATE_KEY")
    configured_address = env.get("WALLET_1_ADDRESS")
    if not private_key or not configured_address:
        raise SystemExit(".env must contain WALLET_1_ADDRESS and WALLET_1_PRIVATE_KEY")

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise SystemExit(f"Cannot connect to Besu RPC at {rpc_url}")
    chain_id = w3.eth.chain_id
    if chain_id != CHAIN_ID:
        raise SystemExit(f"Wrong chain ID: expected {CHAIN_ID}, received {chain_id}")

    account = Account.from_key(private_key)
    if account.address.lower() != configured_address.lower():
        raise SystemExit("Wallet A address does not match its private key")

    compiled = compile_contract()
    factory = w3.eth.contract(abi=compiled["abi"], bytecode=compiled["bin"])
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    gas_price = w3.eth.gas_price
    base_tx = {
        "from": account.address,
        "nonce": nonce,
        "chainId": chain_id,
        "gasPrice": gas_price,
    }
    estimate = factory.constructor().estimate_gas(base_tx)
    gas_limit = (estimate * 120 + 99) // 100
    required = gas_limit * gas_price
    balance = w3.eth.get_balance(account.address)
    print(f"Connected to chain ID {chain_id} at block {w3.eth.block_number}.")
    print(f"Wallet A: {account.address}")
    print(f"Required native gas balance: {required} wei; current balance: {balance} wei.")
    if balance < required:
        raise SystemExit("Insufficient native funds for the estimated deployment gas; nothing was signed or broadcast.")

    unsigned = factory.constructor().build_transaction({**base_tx, "gas": gas_limit})
    signed = account.sign_transaction(unsigned)
    payload = {
        "chainId": chain_id,
        "from": account.address,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "estimatedGas": estimate,
        "transactionHash": Web3.to_hex(signed.hash),
        "rawTransaction": Web3.to_hex(signed.raw_transaction),
        "broadcast": False,
    }
    fd = os.open(OUTPUT_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(payload, output, indent=2)
        output.write("\n")
    print(f"Signed deployment prepared locally in {OUTPUT_FILE.name}; not broadcast.")
    print(f"Transaction hash: {payload['transactionHash']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Deployment preparation failed: {exc}", file=sys.stderr)
        sys.exit(1)
