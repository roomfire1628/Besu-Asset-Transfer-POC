#!/usr/bin/env python3
"""Verify AssetToken balances and prepare (but never broadcast) a Wallet A -> B transfer."""

import json
import os
import sys
from pathlib import Path

from eth_account import Account
from solcx import compile_files, get_installed_solc_versions, install_solc, set_solc_version
from web3 import Web3

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
CONTRACT_FILE = ROOT / "contracts" / "AssetToken.sol"
CONTRACT_ADDRESS = Web3.to_checksum_address("0xAC8E7b9f012d519554FaE7897efBAFC0707ef9C3")
OUTPUT_FILE = ROOT / "transfer-asset.signed-tx.json"
EXPECTED_CHAIN_ID = 1337
TRANSFER_AST = 250
TOKEN_DECIMALS = 18
SOLC_VERSION = "0.8.20"


def load_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def compile_token_abi():
    if SOLC_VERSION not in {str(version) for version in get_installed_solc_versions()}:
        install_solc(SOLC_VERSION)
    set_solc_version(SOLC_VERSION)
    result = compile_files(
        [str(CONTRACT_FILE)],
        output_values=["abi", "bin"],
        import_remappings=[f"@openzeppelin/={ROOT / 'node_modules' / '@openzeppelin'}/"],
        solc_version=SOLC_VERSION,
    )
    contract = next((value for name, value in result.items() if name.endswith(":AssetToken")), None)
    if not contract or not contract.get("abi"):
        raise RuntimeError("Could not compile AssetToken ABI")
    return contract


def verify_balances(w3, token, wallet_a, wallet_b):
    """Read token state only; this function does not construct or send transactions."""
    decimals = token.functions.decimals().call()
    if decimals != TOKEN_DECIMALS:
        raise RuntimeError(f"Expected {TOKEN_DECIMALS} decimals, found {decimals}")
    balance_a = token.functions.balanceOf(wallet_a).call()
    balance_b = token.functions.balanceOf(wallet_b).call()
    total_supply = token.functions.totalSupply().call()
    print(f"Wallet A token balance: {balance_a / 10**decimals:g} AST")
    print(f"Wallet B token balance: {balance_b / 10**decimals:g} AST")
    print(f"Token total supply: {total_supply / 10**decimals:g} AST")
    return balance_a, balance_b, total_supply, decimals


def main():
    if OUTPUT_FILE.exists():
        raise SystemExit(f"Refusing to overwrite existing prepared transfer: {OUTPUT_FILE.name}")
    env = load_env(ENV_FILE)
    rpc_url = env.get("BESU_RPC_URL", "http://127.0.0.1:8545")
    address_a = Web3.to_checksum_address(env["WALLET_1_ADDRESS"])
    address_b = Web3.to_checksum_address(env["WALLET_2_ADDRESS"])
    key_a = env["WALLET_1_PRIVATE_KEY"]
    key_b = env["WALLET_2_PRIVATE_KEY"]

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
    if not w3.is_connected():
        raise SystemExit(f"Cannot connect to Besu RPC at {rpc_url}")
    chain_id = w3.eth.chain_id
    if chain_id != EXPECTED_CHAIN_ID:
        raise SystemExit(f"Expected chain ID {EXPECTED_CHAIN_ID}, got {chain_id}")

    account_a = Account.from_key(key_a)
    account_b = Account.from_key(key_b)
    if account_a.address.lower() != address_a.lower():
        raise SystemExit("Wallet A address does not match its configured key")
    if account_b.address.lower() != address_b.lower():
        raise SystemExit("Wallet B address does not match its configured key")

    compiled = compile_token_abi()
    if not w3.eth.get_code(CONTRACT_ADDRESS):
        raise SystemExit(f"No contract bytecode at {CONTRACT_ADDRESS}")
    token = w3.eth.contract(address=CONTRACT_ADDRESS, abi=compiled["abi"])
    balance_a, balance_b, total_supply, decimals = verify_balances(w3, token, address_a, address_b)
    amount = TRANSFER_AST * (10 ** decimals)
    if balance_a < amount:
        raise SystemExit("Wallet A has insufficient AST; nothing was signed or broadcast")

    nonce = w3.eth.get_transaction_count(address_a, "pending")
    gas_price = w3.eth.gas_price
    transfer = token.functions.transfer(address_b, amount)
    estimate = transfer.estimate_gas({"from": address_a})
    gas_limit = (estimate * 120 + 99) // 100
    required_fee = gas_limit * gas_price
    native_balance = w3.eth.get_balance(address_a)
    print(f"Connected to chain ID {chain_id} at block {w3.eth.block_number}.")
    print(f"Preparing {TRANSFER_AST} AST transfer from Wallet A to Wallet B.")
    print(f"Estimated gas: {estimate}; gas limit: {gas_limit}; gas price: {gas_price} wei.")
    print(f"Required native fee: {required_fee} wei; Wallet A native balance: {native_balance} wei.")
    if native_balance < required_fee:
        raise SystemExit("Wallet A has insufficient native balance for the maximum fee; nothing was signed")

    unsigned = transfer.build_transaction({
        "from": address_a,
        "nonce": nonce,
        "chainId": chain_id,
        "gas": gas_limit,
        "gasPrice": gas_price,
    })
    signed = account_a.sign_transaction(unsigned)
    signed_tx_hash = Web3.to_hex(signed.hash)
    if Account.recover_transaction(signed.raw_transaction).lower() != address_a.lower():
        raise RuntimeError("Locally signed transaction does not recover to Wallet A")
    payload = {
        "chainId": chain_id,
        "from": address_a,
        "to": CONTRACT_ADDRESS,
        "recipient": address_b,
        "tokenAmount": TRANSFER_AST,
        "tokenAmountBaseUnits": amount,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "estimatedGas": estimate,
        "transactionHash": signed_tx_hash,
        "rawTransaction": Web3.to_hex(signed.raw_transaction),
        "broadcast": False,
    }
    fd = os.open(OUTPUT_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(payload, output, indent=2)
        output.write("\n")
    print(f"Prepared signed transfer saved to {OUTPUT_FILE.name}; it has not been broadcast.")
    print(f"Prepared transaction hash: {signed_tx_hash}")
    print(f"Read-only pre-transfer supply: {total_supply / 10**decimals:g} AST.")
    print("Private keys and raw signed transaction bytes were not printed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Transfer preparation failed: {exc}", file=sys.stderr)
        sys.exit(1)
