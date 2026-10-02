"""Offline fixture trigger; does not contact production layers."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if sys.argv[1:] != ['scaffold-smoke']:
    raise SystemExit('Usage: python scenarios/run.py scaffold-smoke')
events = json.loads((root / 'contracts/examples/scaffold-smoke.json').read_text())
now = datetime.now(timezone.utc)
path = root / 'logs' / ('scaffold-smoke-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.jsonl')
with path.open('w', encoding='utf-8') as log:
    for event in events:
        record = dict(event, timestamp=datetime.now(timezone.utc).isoformat(), scenario='scaffold-smoke', mode='offline-fixture')
        log.write(json.dumps(record) + '\n')
        print(record['timestamp'], record['layer'], record['type'])
print('Synthetic fixture log:', path)
