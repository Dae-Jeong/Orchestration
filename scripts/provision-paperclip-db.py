"""One-time dedicated DB bootstrap; never prints credentials."""
import os
from pathlib import Path
import secrets
import subprocess

root = Path(__file__).resolve().parent.parent
env_path = root / '.env.paperclip'
if env_path.exists():
    raise SystemExit('Credentials already exist; refusing to replace them.')

def sql(query, database='postgres'):
    return subprocess.run(
        ['docker', 'exec', '-i', 'thready-postgres', 'psql', '-X', '-qAt',
         '-v', 'ON_ERROR_STOP=1', '-U', 'thready', '-d', database],
        input=query, text=True, capture_output=True, check=True).stdout.strip()

name = 'orchestration_paperclip'
if sql(f"SELECT 1 FROM pg_roles WHERE rolname='{name}'") or sql(
    f"SELECT 1 FROM pg_database WHERE datname='{name}'"):
    raise SystemExit('Dedicated role or database already exists; inspect before retrying.')
password = secrets.token_hex(32)
os.umask(0o077)
with env_path.open('x') as target:
    target.write(f'DATABASE_URL=postgresql://{name}:{password}@127.0.0.1:5433/{name}\n')
    target.write(f'PAPERCLIP_HOME={root}/.paperclip\n')
    target.write('PORT=13100\nHOST=127.0.0.1\nSERVE_UI=true\n')
    target.write('HEARTBEAT_SCHEDULER_ENABLED=false\nPAPERCLIP_DB_BACKUP_ENABLED=false\n')
    target.write('DO_NOT_TRACK=1\nPAPERCLIP_OPEN_ON_LISTEN=false\n')
try:
    sql(f"CREATE ROLE {name} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;")
    sql(f'CREATE DATABASE {name} OWNER {name};')
    sql(f'REVOKE ALL ON DATABASE {name} FROM PUBLIC;')
    sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC; CREATE EXTENSION pg_trgm; CREATE EXTENSION fuzzystrmatch;', name)
except subprocess.CalledProcessError:
    raise SystemExit('DB provisioning failed. Credentials retained privately; inspect DB state before retry.')
print('Dedicated database and restricted login created; credentials saved privately.')
