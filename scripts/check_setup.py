"""Validate the scaffold's required files and synthetic message sequence."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
required = ['README.md', 'INTEGRATION.md', 'TESTBOOK.md', 'CONTRIBUTING.md', '.github/CODEOWNERS', 'mockups/testing/README.md']
for layer in ('twin', 'brain', 'guardian'):
    required += [f'{layer}/README.md', f'{layer}/INTERFACE.md', f'{layer}/src/main.py', f'{layer}/mocks/partners.json', f'{layer}/tests/README.md']
missing = [p for p in required if not (root / p).is_file()]
if missing:
    raise SystemExit('Missing required files: ' + ', '.join(missing))
events = json.loads((root / 'contracts/examples/scaffold-smoke.json').read_text())
assert [e['type'] for e in events] == ['reading', 'trust_verdict', 'decision', 'action_result']
assert len({e['correlation_id'] for e in events}) == 1
assert all(e['synthetic'] is True for e in events)
print('Scaffold checks passed; production integration remains pending.')
