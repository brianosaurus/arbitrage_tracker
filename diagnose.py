#!/usr/bin/env python3
"""
Diagnostic script — process one block and dump pipeline state at each stage.
Deploy alongside other .py files and run: python3 diagnose.py
"""

import asyncio
import base58
import logging
import sys

from config import Config
from block_fetcher import BlockFetcher
from swap_detector import SwapDetector
from constants import DEX_PROGRAMS, SUPPORTED_DEXS, SWAP_DISCRIMINATORS

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)


async def main():
    config = Config()
    fetcher = BlockFetcher(config.grpc_endpoint, config.grpc_token)
    detector = SwapDetector()

    log.info("Waiting for one block...")
    async for slot, block in fetcher.follow_confirmed():
        log.info(f"\n{'='*70}")
        log.info(f"SLOT: {slot}")
        log.info(f"block type: {type(block).__name__}")
        log.info(f"has transactions: {hasattr(block, 'transactions')}")

        if not hasattr(block, 'transactions'):
            log.info("NO TRANSACTIONS ATTR — skipping")
            continue

        txs = block.transactions
        log.info(f"transaction count: {len(txs)}")

        if not txs:
            log.info("Empty block, waiting for next...")
            continue

        # Analyze first 20 transactions in detail
        swap_count = 0
        arb_candidates = 0

        for i, tx in enumerate(txs):
            verbose = i < 5  # verbose for first 5 txs

            if verbose:
                log.info(f"\n--- TX {i} ---")
                log.info(f"  tx type: {type(tx).__name__}")
                log.info(f"  has .signature: {hasattr(tx, 'signature')}")
                log.info(f"  has .transaction: {hasattr(tx, 'transaction')}")
                log.info(f"  has .meta: {hasattr(tx, 'meta')}")

            # 1. Signature extraction
            try:
                sig = base58.b58encode(tx.signature).decode('utf-8')
                if verbose:
                    log.info(f"  signature: {sig[:20]}...")
            except Exception as e:
                if verbose:
                    log.info(f"  SIGNATURE FAIL: {e}")
                    # Try alternative paths
                    try:
                        sig2 = base58.b58encode(tx.transaction.signatures[0]).decode('utf-8')
                        log.info(f"  ALT .transaction.signatures[0]: {sig2[:20]}...")
                    except Exception as e2:
                        log.info(f"  ALT ALSO FAILED: {e2}")
                continue

            # 2. Error check
            meta = tx.meta
            if verbose:
                log.info(f"  meta type: {type(meta).__name__}")
                log.info(f"  meta.err type: {type(meta.err).__name__}")
                log.info(f"  meta.err value: {repr(meta.err)}")
                log.info(f"  meta.err bool: {bool(meta.err)}")
                try:
                    log.info(f"  meta.err len: {len(meta.err)}")
                except TypeError:
                    log.info(f"  meta.err has no len()")
                try:
                    log.info(f"  meta.HasField('err'): {meta.HasField('err')}")
                except Exception as e:
                    log.info(f"  HasField err: {e}")
                try:
                    log.info(f"  meta.err.err: {repr(meta.err.err)}")
                except Exception as e:
                    log.info(f"  meta.err.err: {e}")

            # Check if tx failed using various methods
            is_failed = False
            try:
                is_failed = meta.err and len(meta.err) > 0
            except TypeError:
                # meta.err is a message, not bytes — try HasField
                try:
                    is_failed = meta.HasField('err')
                except:
                    pass

            if verbose:
                log.info(f"  is_failed: {is_failed}")

            if is_failed:
                continue

            # 3. Signer extraction
            try:
                message = tx.transaction.message
                account_keys = message.account_keys
                if verbose:
                    log.info(f"  account_keys count: {len(account_keys)}")
                    if account_keys:
                        first_key = account_keys[0]
                        log.info(f"  first_key type: {type(first_key).__name__}, len: {len(first_key)}")
                        signer = base58.b58encode(first_key).decode('utf-8')
                        log.info(f"  signer: {signer[:20]}...")
            except Exception as e:
                if verbose:
                    log.info(f"  SIGNER FAIL: {e}")
                continue

            # 4. Instructions
            try:
                instructions = message.instructions
                if verbose:
                    log.info(f"  top-level instructions: {len(instructions)}")
                    if instructions:
                        instr = instructions[0]
                        log.info(f"    instr type: {type(instr).__name__}")
                        log.info(f"    has .program_id_index: {hasattr(instr, 'program_id_index')}")
                        log.info(f"    has .accounts: {hasattr(instr, 'accounts')}")
                        log.info(f"    has .data: {hasattr(instr, 'data')}")
                        log.info(f"    program_id_index: {instr.program_id_index}")
                        log.info(f"    data type: {type(instr.data).__name__}, len: {len(instr.data)}")
                        log.info(f"    accounts type: {type(instr.accounts).__name__}, len: {len(instr.accounts)}")
            except Exception as e:
                if verbose:
                    log.info(f"  INSTRUCTIONS FAIL: {e}")

            # 5. Inner instructions
            try:
                inner = meta.inner_instructions
                if verbose:
                    log.info(f"  inner_instruction groups: {len(inner)}")
                    total_inner = sum(len(g.instructions) for g in inner)
                    log.info(f"  total inner instructions: {total_inner}")
            except Exception as e:
                if verbose:
                    log.info(f"  INNER INSTRUCTIONS FAIL: {e}")

            # 6. Check for DEX programs
            try:
                all_program_ids = set()
                for instr in message.instructions:
                    pid = detector.get_program_id(tx, instr.program_id_index)
                    if pid:
                        all_program_ids.add(pid)
                for ig in meta.inner_instructions:
                    for instr in ig.instructions:
                        pid = detector.get_program_id(tx, instr.program_id_index)
                        if pid:
                            all_program_ids.add(pid)

                dex_hits = {pid: DEX_PROGRAMS.get(pid) for pid in all_program_ids if pid in DEX_PROGRAMS}
                if dex_hits:
                    if verbose or True:  # always log DEX hits
                        log.info(f"  TX {i}: DEX programs found: {dex_hits}")

                    # Try full swap detection
                    swaps = detector.analyze_transaction(tx)
                    log.info(f"  TX {i}: swaps detected: {len(swaps)}")
                    if len(swaps) >= 2:
                        arb_candidates += 1
                        log.info(f"  TX {i}: *** ARB CANDIDATE ({len(swaps)} swaps) ***")
                    for s in swaps:
                        log.info(f"    swap: dex={s['dex']}, pool={s.get('pool_address','?')}, "
                                f"vaults={len(s.get('vault_balance_changes',{}))}, "
                                f"type={s.get('swap_type','?')}")

                    swap_count += len(swaps)
            except Exception as e:
                if verbose:
                    log.info(f"  DEX CHECK FAIL: {e}")
                    import traceback
                    traceback.print_exc()

            # 7. Token balances (check format)
            if verbose:
                try:
                    pre_tb = meta.pre_token_balances
                    log.info(f"  pre_token_balances count: {len(pre_tb)}")
                    if pre_tb:
                        b = pre_tb[0]
                        log.info(f"    balance type: {type(b).__name__}")
                        log.info(f"    .account_index: {b.account_index}")
                        log.info(f"    .mint: {b.mint}")
                        log.info(f"    .owner: {b.owner}")
                        log.info(f"    .ui_token_amount.amount: {repr(b.ui_token_amount.amount)}")
                        log.info(f"    .ui_token_amount.decimals: {b.ui_token_amount.decimals}")
                except Exception as e:
                    log.info(f"  TOKEN BALANCE FAIL: {e}")

        log.info(f"\n{'='*70}")
        log.info(f"BLOCK SUMMARY for slot {slot}:")
        log.info(f"  Total txs: {len(txs)}")
        log.info(f"  Total swaps found: {swap_count}")
        log.info(f"  Arb candidates (2+ swaps): {arb_candidates}")
        log.info(f"{'='*70}")

        # Process 3 blocks then stop
        if slot:
            break


if __name__ == '__main__':
    asyncio.run(main())
