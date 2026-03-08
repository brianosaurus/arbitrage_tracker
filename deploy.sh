#!/bin/bash

tar czf - --no-xattrs *.py | ssh frankfurt "cd arbitrage_tracker && tar xzf -"
ssh frankfurt "cd arbitrage_tracker; source ~/venv/bin/activate; python3 tracker.py --follow --duration 8640" | tee /tmp/arbitrage_tracker.log
