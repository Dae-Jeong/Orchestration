"""Read-only Paperclip Codex readiness check; never dispatches a model or MCP call."""
import argparse
import json
from pathlib import Path
import tomllib
from urllib.request import urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--agent-id', required=True)
parser.add_argument('--instance-root', type=Path, required=True)
args = parser.parse_args()
with urlopen('http://127.0.0.1:13100/api/agents/' + args.agent_id, timeout=10) as response:
    agent = json.load(response)
if agent['adapterType'] != 'codex_local':
    raise SystemExit('Expected a codex_local agent')
env = agent['adapterConfig'].get('env', {})
configured = env.get('CODEX_HOME')
if isinstance(configured, dict):
    configured = configured.get('value') if configured.get('type') == 'plain' else None
company_root = args.instance_root / 'companies' / agent['companyId']
# Installed adapter uses company home by default; an explicit override takes precedence.
home = Path(configured) if configured else company_root / 'codex-home'
per_agent = company_root / 'agents' / args.agent_id / 'codex-home'
servers = {}
if (home / 'config.toml').is_file():
    config = tomllib.loads((home / 'config.toml').read_text())
    for name in ('pencil', 'uibowl'):
        value = config.get('mcp_servers', {}).get(name)
        servers[name] = {'configured': value is not None,
                         'enabled': bool(value and value.get('enabled', True))}
skills = home / 'skills'
readable = {}
for name in ('squad-model', 'product-workflow'):
    entry = skills / name / 'SKILL.md'
    readable[name] = bool(entry.is_file() and entry.read_text())
workflow = env.get('PRODUCT_WORKFLOW_FILE')
if isinstance(workflow, dict):
    workflow = workflow.get('value') if workflow.get('type') == 'plain' else None
print(json.dumps({
    'agent_status': agent['status'], 'adapter': agent['adapterType'],
    'effective_home_exists': home.is_dir(), 'per_agent_home_exists': per_agent.is_dir(),
    'required_servers': servers,
    'home_scope': 'explicit_override' if configured else 'default_managed',
    'skills_readable': readable,
    'canonical_workflow_read': bool(workflow and Path(workflow).is_file() and Path(workflow).read_text()),
    'skill_entries': sorted(p.name for p in skills.iterdir()) if skills.is_dir() else [],
    'model_calls': 0, 'mcp_calls': 0,
    'connection_verified': False,
    'limitation': 'Read-only configuration inspection, not MCP handshake or model execution',
}))
