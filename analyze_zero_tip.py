#!/usr/bin/env python3
"""Analyze arbitrage transactions with zero Jito tip.

Uses SQLite DB (swap_legs has full mint addresses) joined with
arbitrage_transactions to get accurate token identification.
Falls back to CSV-only analysis if DB is unavailable.
"""

import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "arb_tracker.csv"
DB_PATH = BASE_DIR / "arb_tracker.db"

# Well-known token mints (matches constants.py)
KNOWN_MINTS = {
    "So11111111111111111111111111111111111111112": "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "USDH1SM1ojwWUga67PGrgFWUHibbjqMvuMaDkRJTgkX": "USDH",
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "ETH",
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh": "BTC",
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "RAY",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj": "stSOL",
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "JTO",
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": "jitoSOL",
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": "bSOL",
    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": "jupSOL",
}


def resolve_mint(mint: str) -> str:
    """Resolve a mint address to a human-readable symbol."""
    if not mint:
        return "unknown"
    sym = KNOWN_MINTS.get(mint)
    if sym:
        return sym
    return mint  # Return full address for later grouping


def build_mint_lookup_from_db(db_path: Path) -> dict:
    """Build signature -> first-leg token_in_mint lookup from the DB."""
    if not db_path.exists():
        return {}
    print(f"Loading mint addresses from {db_path}...")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        SELECT signature, token_in_mint
        FROM swap_legs
        WHERE leg_index = 0
    """)
    lookup = {}
    for sig, mint in cursor:
        lookup[sig] = mint or ""
    conn.close()
    print(f"  Loaded {len(lookup):,} mint lookups from DB")
    return lookup


def analyze(csv_path: Path = CSV_PATH, db_path: Path = DB_PATH):
    mint_lookup = build_mint_lookup_from_db(db_path)
    use_db = bool(mint_lookup)

    total_rows = 0
    zero_tip_rows = 0
    token_counts = Counter()       # resolved symbol -> count
    full_mint_counts = Counter()   # full mint address -> count (for unknowns)
    dex_pair_counts = Counter()
    signer_counts = Counter()

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            tip_str = row.get("jito_tip_sol") or ""
            tip = float(tip_str) if tip_str.strip() else 0.0
            if tip != 0.0:
                continue
            zero_tip_rows += 1

            # Resolve token: prefer DB mint, fall back to CSV token column
            sig = row["signature"]
            if use_db and sig in mint_lookup:
                full_mint = mint_lookup[sig]
                token = resolve_mint(full_mint)
            else:
                token = row["token"]
                full_mint = token

            token_counts[token] += 1
            if token not in KNOWN_MINTS.values() and token != "unknown":
                full_mint_counts[full_mint] += 1

            dex_pair = f"{row['dex_a']} -> {row['dex_b']}"
            dex_pair_counts[dex_pair] += 1
            signer_counts[row["signer"]] += 1

    # --- Report ---
    print("=" * 70)
    print("ZERO JITO TIP ARBITRAGE ANALYSIS")
    print(f"  Data source: {'DB + CSV' if use_db else 'CSV only'}")
    print("=" * 70)

    print(f"\nTotal transactions:           {total_rows:>12,}")
    print(f"Zero-tip transactions:        {zero_tip_rows:>12,}")
    pct = (zero_tip_rows / total_rows * 100) if total_rows else 0
    print(f"Zero-tip percentage:          {pct:>11.2f}%")

    # Token breakdown — top 50 with full mint addresses
    print(f"\n{'─' * 90}")
    print(f"TOKEN BREAKDOWN  ({len(token_counts)} unique tokens, showing top 50)")
    print(f"{'─' * 90}")
    print(f"{'Token':<48} {'Count':>10} {'% of Zero-Tip':>12}  {'Full Mint (if not well-known)'}")
    print(f"{'─' * 48} {'─' * 10} {'─' * 12}  {'─' * 16}")
    for token, count in token_counts.most_common(50):
        pct_zt = count / zero_tip_rows * 100 if zero_tip_rows else 0
        # Show full mint for non-well-known tokens
        if token in KNOWN_MINTS.values() or token == "unknown":
            mint_display = ""
        else:
            mint_display = token if len(token) > 20 else ""
        # Use symbol for display, truncate if needed
        display = token[:46] if len(token) > 46 else token
        print(f"{display:<48} {count:>10,} {pct_zt:>11.2f}%  {mint_display}")

    # Count unknown tokens
    unknown_count = token_counts.get("unknown", 0)
    if unknown_count:
        print(f"\n  'unknown' = {unknown_count:,} rows where token_in_mint was empty/null")

    # DEX pair breakdown
    print(f"\n{'─' * 70}")
    print(f"DEX PAIR ROUTES  ({len(dex_pair_counts)} unique routes)")
    print(f"{'─' * 70}")
    print(f"{'Route':<45} {'Count':>10} {'% of Zero-Tip':>12}")
    print(f"{'─' * 45} {'─' * 10} {'─' * 12}")
    for route, count in dex_pair_counts.most_common():
        pct_zt = count / zero_tip_rows * 100 if zero_tip_rows else 0
        print(f"{route:<45} {count:>10,} {pct_zt:>11.2f}%")

    # Top signers
    print(f"\n{'─' * 70}")
    print(f"TOP 20 SIGNERS  ({len(signer_counts)} unique signers)")
    print(f"{'─' * 70}")
    print(f"{'Signer':<45} {'Count':>10} {'% of Zero-Tip':>12}")
    print(f"{'─' * 45} {'─' * 10} {'─' * 12}")
    for signer, count in signer_counts.most_common(20):
        pct_zt = count / zero_tip_rows * 100 if zero_tip_rows else 0
        print(f"{signer:<45} {count:>10,} {pct_zt:>11.2f}%")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    csv_p = Path(sys.argv[1]) if len(sys.argv) > 1 else CSV_PATH
    db_p = Path(sys.argv[2]) if len(sys.argv) > 2 else DB_PATH
    if not csv_p.exists():
        print(f"Error: {csv_p} not found")
        sys.exit(1)
    analyze(csv_p, db_p)
