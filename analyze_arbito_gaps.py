#!/usr/bin/env python3
"""Analyze zero-tip arbitrage opportunities vs what arbito can capture.

Cross-references tracker DB with arbito's KLend-supported tokens to show:
1. How many zero-tip arbs use tokens arbito CAN trade
2. Which token pairs have the most uncaptured volume
3. DEX route breakdown for capturable vs non-capturable
4. Time distribution of opportunities
"""

import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB_PATH = Path(__file__).parent / "arb_tracker.db"

# Arbito's KLend-supported mints (from arbito/constants.py)
KLEND_MINTS = {
    "So11111111111111111111111111111111111111112": "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": "jitoSOL",
    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": "jupSOL",
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": "bSOL",
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "ETH",
}

KLEND_MINT_SET = set(KLEND_MINTS.keys())


def analyze(db_path: Path = DB_PATH):
    if not db_path.exists():
        print(f"Error: {db_path} not found")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))

    # --- Basic stats ---
    total = conn.execute("SELECT COUNT(*) FROM arbitrage_transactions").fetchone()[0]
    zero_tip = conn.execute(
        "SELECT COUNT(*) FROM arbitrage_transactions WHERE has_jito_tip = 0"
    ).fetchone()[0]
    with_tip = total - zero_tip

    print("=" * 80)
    print("ARBITO GAP ANALYSIS: Zero-Tip Arbs vs Arbito Capabilities")
    print("=" * 80)
    print(f"\nTotal arb transactions:       {total:>12,}")
    print(f"Zero-tip:                     {zero_tip:>12,}  ({zero_tip/total*100:.1f}%)")
    print(f"With tip:                     {with_tip:>12,}  ({with_tip/total*100:.1f}%)")

    # --- For zero-tip arbs, check if EITHER token in the pair is KLend-supported ---
    # This means arbito could potentially flash-loan that token and arb
    print(f"\n{'─' * 80}")
    print("ZERO-TIP ARBS: Can arbito trade them?")
    print(f"{'─' * 80}")
    print("(An arb is 'capturable' if at least one token in the pair is KLend-supported)")

    # Get all zero-tip arb signatures with their first leg tokens
    rows = conn.execute("""
        SELECT at.signature, at.slot, at.signer,
               sl.token_in_mint, sl.token_out_mint, sl.dex
        FROM arbitrage_transactions at
        JOIN swap_legs sl ON at.signature = sl.signature AND sl.leg_index = 0
        WHERE at.has_jito_tip = 0
    """).fetchall()

    capturable = 0
    not_capturable = 0
    capturable_by_start_token = Counter()
    capturable_by_dex = Counter()
    not_capturable_by_dex = Counter()
    capturable_pairs = Counter()  # (klend_token, other_token) -> count
    not_capturable_pairs = Counter()

    # Also get the second leg to understand the full pair
    # Build a lookup: sig -> list of (token_in, token_out, dex)
    all_legs = conn.execute("""
        SELECT sl.signature, sl.leg_index, sl.token_in_mint, sl.token_out_mint, sl.dex
        FROM swap_legs sl
        JOIN arbitrage_transactions at ON at.signature = sl.signature
        WHERE at.has_jito_tip = 0
        ORDER BY sl.signature, sl.leg_index
    """).fetchall()

    # Build sig -> legs mapping
    sig_legs = {}
    for sig, idx, tin, tout, dex in all_legs:
        if sig not in sig_legs:
            sig_legs[sig] = []
        sig_legs[sig].append((idx, tin, tout, dex))

    for sig, slot, signer, token_in, token_out, dex in rows:
        legs = sig_legs.get(sig, [])
        # Collect all unique mints in this arb
        all_mints = set()
        all_dexes = []
        for _, tin, tout, d in legs:
            if tin:
                all_mints.add(tin)
            if tout:
                all_mints.add(tout)
            all_dexes.append(d)

        klend_in_pair = all_mints & KLEND_MINT_SET
        route = " -> ".join(all_dexes) if all_dexes else dex

        if klend_in_pair:
            capturable += 1
            # Which KLend token would be the start token?
            for m in klend_in_pair:
                capturable_by_start_token[KLEND_MINTS[m]] += 1
            # Simplify route to first->last dex
            simple_route = f"{all_dexes[0]} -> {all_dexes[-1]}" if len(all_dexes) > 1 else dex
            capturable_by_dex[simple_route] += 1
            # Token pair: klend token vs non-klend token
            non_klend = all_mints - KLEND_MINT_SET
            for km in klend_in_pair:
                for nk in non_klend:
                    short_nk = nk[:12] + "..." if len(nk) > 16 else nk
                    capturable_pairs[(KLEND_MINTS[km], short_nk)] += 1
        else:
            not_capturable += 1
            simple_route = f"{all_dexes[0]} -> {all_dexes[-1]}" if len(all_dexes) > 1 else dex
            not_capturable_by_dex[simple_route] += 1
            # What tokens are in non-capturable arbs?
            for m in all_mints:
                short = m[:12] + "..." if len(m) > 16 else m
                not_capturable_pairs[short] += 1

    pct_cap = capturable / zero_tip * 100 if zero_tip else 0
    pct_not = not_capturable / zero_tip * 100 if zero_tip else 0
    print(f"\n  Capturable (KLend token in pair): {capturable:>10,}  ({pct_cap:.1f}%)")
    print(f"  NOT capturable (no KLend token):  {not_capturable:>10,}  ({pct_not:.1f}%)")

    # Capturable by start token
    print(f"\n{'─' * 80}")
    print("CAPTURABLE ARBS BY KLEND START TOKEN")
    print(f"{'─' * 80}")
    print("(Token arbito could flash-loan to start the arb)")
    print(f"{'Token':<15} {'Count':>10} {'% of Capturable':>15}")
    print(f"{'─' * 15} {'─' * 10} {'─' * 15}")
    for token, count in capturable_by_start_token.most_common():
        print(f"{token:<15} {count:>10,} {count/capturable*100:>14.1f}%")

    # Capturable by DEX route
    print(f"\n{'─' * 80}")
    print("CAPTURABLE ARBS BY DEX ROUTE")
    print(f"{'─' * 80}")
    print(f"{'Route':<45} {'Count':>10} {'% of Capturable':>15}")
    print(f"{'─' * 45} {'─' * 10} {'─' * 15}")
    for route, count in capturable_by_dex.most_common(20):
        print(f"{route:<45} {count:>10,} {count/capturable*100:>14.1f}%")

    # NOT capturable by DEX route
    print(f"\n{'─' * 80}")
    print("NON-CAPTURABLE ARBS BY DEX ROUTE")
    print(f"{'─' * 80}")
    print(f"{'Route':<45} {'Count':>10} {'% of Non-Cap':>15}")
    print(f"{'─' * 45} {'─' * 10} {'─' * 15}")
    for route, count in not_capturable_by_dex.most_common(20):
        print(f"{route:<45} {count:>10,} {count/not_capturable*100:>14.1f}%")

    # Top capturable token pairs
    print(f"\n{'─' * 80}")
    print("TOP 30 CAPTURABLE TOKEN PAIRS  (KLend token + other token)")
    print(f"{'─' * 80}")
    print(f"{'KLend Token':<10} {'Other Token':<48} {'Count':>10}")
    print(f"{'─' * 10} {'─' * 48} {'─' * 10}")
    for (klend_tok, other_tok), count in capturable_pairs.most_common(30):
        print(f"{klend_tok:<10} {other_tok:<48} {count:>10,}")

    # Top non-capturable tokens (what tokens are we missing?)
    print(f"\n{'─' * 80}")
    print("TOP 30 TOKENS IN NON-CAPTURABLE ARBS  (what's arbito missing?)")
    print(f"{'─' * 80}")
    print(f"{'Token Mint':<48} {'Appearances':>10}")
    print(f"{'─' * 48} {'─' * 10}")
    for tok, count in not_capturable_pairs.most_common(30):
        print(f"{tok:<48} {count:>10,}")

    # --- Profitability of zero-tip arbs ---
    print(f"\n{'─' * 80}")
    print("PROFITABILITY OF ZERO-TIP ARBS")
    print(f"{'─' * 80}")
    prof_rows = conn.execute("""
        SELECT is_profitable, COUNT(*)
        FROM arbitrage_transactions
        WHERE has_jito_tip = 0
        GROUP BY is_profitable
    """).fetchall()
    for is_prof, cnt in prof_rows:
        label = "Profitable" if is_prof else "Not profitable"
        print(f"  {label:<20} {cnt:>10,}  ({cnt/zero_tip*100:.1f}%)")

    conn.close()
    print(f"\n{'=' * 80}")


if __name__ == "__main__":
    db_p = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    analyze(db_p)
