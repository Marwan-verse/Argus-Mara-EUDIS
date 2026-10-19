"""Copy shared exercise inputs into the film without modifying the contracts."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent
repository = root.parent
exercise = json.loads((repository / 'demo/scenario.json').read_text(encoding='utf-8'))
assessment = json.loads((repository / 'demo/alerts.json').read_text(encoding='utf-8'))['alerts'][0]
(root / 'src/evidence.ts').write_text('export const exercise = '+json.dumps(exercise)+';\nexport const assessment = '+json.dumps(assessment)+';\n', encoding='utf-8')
print('Updated the film evidence snapshot; shared demo files are unchanged.')
