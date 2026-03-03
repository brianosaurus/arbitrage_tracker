# Arbitrage Tracker - Implementation

## Completed
- [x] Symlinks: `proto/` -> arbito/proto, `generated/` -> arbito/generated
- [x] Copied protobuf files: geyser_pb2.py, geyser_pb2_grpc.py, solana_storage_pb2.py, solana_storage_pb2_grpc.py
- [x] `requirements.txt` — subset of arbito deps (grpc, solana, base58, dotenv, aiohttp)
- [x] `.env.example` — template with SOLANA_RPC_URL, GRPC_ENDPOINT, GRPC_TOKEN
- [x] `constants.py` — DEX program IDs, swap discriminators, token mints, Jito/bot wallets, system accounts
- [x] `config.py` — simplified dataclass with env loading (RPC/gRPC only, no signing)
- [x] `swap_detector.py` — ported from arbito, all swap detection methods
- [x] `grpc_utils.py` — extract_signer, should_skip_transaction, extract_addresses, contains_jito_tip_account
- [x] `block_fetcher.py` — gRPC block streaming with follow_confirmed() and fetch_slot_range()
- [x] `transaction_analyzer.py` — core arb detection: SwapLeg, ArbitrageTransaction dataclasses, balance change analysis
- [x] `db.py` — SQLite with arbitrage_transactions, swap_legs, scan_progress tables
- [x] `display.py` — console output with swap legs, net P&L, Solscan links, progress indicator
- [x] `tracker.py` — CLI entry point with argparse (--follow, --slot-range, --db, --min-swaps, --signer, --verbose)

## Verification
- [x] `python tracker.py --help` — CLI works
- [x] All module imports pass cleanly
- [x] Database creates tables correctly
- [ ] `python tracker.py --follow --verbose` — connects to gRPC, receives blocks, detects arbs (needs .env with valid credentials)
- [ ] `python tracker.py --slot-range <known-range>` — scans historical blocks (needs .env with valid credentials)
