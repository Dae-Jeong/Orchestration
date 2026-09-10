"""Seed synthetic backlog issues through Paperclip's API; does not run agents."""
import argparse
import json
from pathlib import Path
import runpy
import urllib.request

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--company-id', required=True)
parser.add_argument('--api-base', default='http://127.0.0.1:13100')
args = parser.parse_args()
if args.api_base != 'http://127.0.0.1:13100':
    raise SystemExit('This fixture is restricted to the local pilot URL.')

def api(path, data=None):
    request = urllib.request.Request(args.api_base + '/api' + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json', 'Origin': args.api_base})
    with urllib.request.urlopen(request) as response:
        return json.load(response)

data = json.loads((root / 'examples/pilot.json').read_text())
runpy.run_path(str(root / 'scripts/check-contracts.py'))['validate'](data)
existing = api(f'/companies/{args.company_id}/issues')
mapping = {}
for task in data['tasks']:
    title = task['task_id'] + ': ' + task['title']
    matches = [issue for issue in existing if issue['title'] == title]
    if len(matches) > 1:
        raise SystemExit('Duplicate pilot IDs; inspect before continuing.')
    if matches:
        issue = matches[0]
    else:
        payload = {'title': title, 'status': 'backlog',
                   'description': 'Synthetic proposal; no product execution authorized.\n\n```json\n'
                       + json.dumps(task, ensure_ascii=False, indent=2) + '\n```',
                   'blockedByIssueIds': [mapping[dep]['id'] for dep in task['depends_on']],
                   'responsibleUserId': 'local-board'}
        if task['role'] == 'user':
            payload['executionPolicy'] = {'stages': [{'type': 'approval',
                'participants': [{'type': 'user', 'userId': 'local-board'}]}], 'maxReviewRounds': 3}
        issue = api(f'/companies/{args.company_id}/issues', payload)
    mapping[task['task_id']] = {'id': issue['id'], 'identifier': issue['identifier']}
    (root / '.paperclip/pilot-map.json').write_text(json.dumps(mapping, indent=2))
print(json.dumps(mapping, indent=2))
