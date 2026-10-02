"""Standalone synthetic partner-fixture check; replace with layer service."""
import json
from pathlib import Path

layer_dir = Path(__file__).resolve().parents[1]
partners = json.loads((layer_dir / 'mocks/partners.json').read_text())
expected = {'twin', 'brain', 'guardian'} - {layer_dir.name}
if set(partners) != expected or not all(partners.values()):
    raise SystemExit('Both partner fixtures must be present')
print(layer_dir.name + ': offline fixture check passed for ' + ', '.join(sorted(partners)))
print('Domain service and transport are not implemented yet.')
