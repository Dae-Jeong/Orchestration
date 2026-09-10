"""Free process-adapter probe: read local skill and validate synthetic contracts."""
import hashlib
import json
import os
from pathlib import Path
import runpy

root = Path(__file__).resolve().parent.parent
skill = root / 'skills/squad-model/SKILL.md'
reference = skill.parent / 'references/model.md'
model = runpy.run_path(str(root / 'scripts/check-contracts.py'))
count = model['validate'](json.loads((root / 'examples/pilot.json').read_text()))
workflow = os.environ.get('PRODUCT_WORKFLOW_FILE')
workflow_read = bool(workflow and Path(workflow).is_file())
if workflow_read:
    Path(workflow).read_text()
result = {'probe': 'squad-model', 'contracts_valid': count,
          'skill_sha256': hashlib.sha256(skill.read_bytes()).hexdigest(),
          'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
          'canonical_workflow_read': workflow_read,
          'model_calls': 0, 'limitations': 'File access and validation only; no LLM comprehension claim'}
print(json.dumps(result))
