"""Validate contract records; never dispatches work or changes Paperclip state."""
import hashlib
import json
import sys
from pathlib import Path

def digest(contract):
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()

def validate(data):
    tasks = data['tasks']
    by_id = {t['task_id']: t for t in tasks}
    if len(by_id) != len(tasks):
        raise ValueError('Duplicate task_id')
    visiting, visited = set(), set()
    def visit(key):
        if key in visiting:
            raise ValueError('Dependency cycle')
        if key in visited:
            return
        if key not in by_id:
            raise ValueError(f'Missing dependency: {key}')
        visiting.add(key)
        for dep in by_id[key]['depends_on']:
            visit(dep)
        visiting.remove(key)
        visited.add(key)
    for task in tasks:
        key, contract = task['task_id'], task['contract']
        visit(key)
        if not key or task['role'] not in ('pm-planning', 'design', 'development', 'verification', 'user'):
            raise ValueError('Missing ID or invalid role')
        if type(contract['revision']) is not int or contract['revision'] < 1:
            raise ValueError('Invalid revision')
        for field in ('acceptance', 'verification', 'authority', 'resources', 'decision'):
            if not contract.get(field):
                raise ValueError(f'Missing contract field: {field}')
        if contract['decision']['status'] not in ('proposed', 'agreed'):
            raise ValueError('Invalid decision status')
        if contract['decision']['status'] == 'agreed' and not all(
            contract['decision'].get(k) for k in ('human', 'reference')):
            raise ValueError('Agreed contract lacks decision evidence')
        for resource in contract['resources']:
            if not resource['key'] or resource['mode'] not in ('read', 'write'):
                raise ValueError('Invalid resource claim')
        if task['criteria_hash'] != digest(contract):
            raise ValueError(f'Stale contract hash: {key}')
        for evidence in task.get('evidence', []):
            if evidence['revision'] != contract['revision'] or evidence['criteria_hash'] != task['criteria_hash']:
                raise ValueError(f'Stale evidence: {key}')
            if not evidence.get('reference') or not evidence.get('verifier') or evidence.get('result') not in ('pass', 'fail'):
                raise ValueError('Incomplete evidence')
    return len(tasks)

if __name__ == '__main__':
    data = json.loads(Path(sys.argv[1]).read_text())
    print(f'{validate(data)} contracts valid; no work dispatched')
