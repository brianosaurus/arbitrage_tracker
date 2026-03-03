#!/bin/bash

tar czf - --no-xattrs *.py dex/*.py scripts/*.py | ssh frankfurt "cd arbitrage_tracker && tar xzf -"
ssh frankfurt "cd arbitrage_tracker; source venv/bin/activate; python python tracker.py --follow --duration 10" | tee /tmp/arbitrage_tracker.log
