"""Detached execution supervisor. Receipts survive scheduler/Orca reconnects."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run(spec_path):
    spec_path = Path(spec_path).resolve()
    folder = spec_path.parent
    spec = json.loads(spec_path.read_text())
    with (folder / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        # A started receipt without an exit is ambiguous: never run it again.
        if (folder / "started.json").exists() or (folder / "exited.json").exists():
            return 0
        atomic_json(folder / "started.json", dict(attempt=spec["attempt"], pid=os.getpid(), at=time.time()))
        env = dict(os.environ, SCHEDULER_ATTEMPT=spec["attempt"], SCHEDULER_TASK=spec["task"],
                   SCHEDULER_TASK_PATH=spec["task_path"], SCHEDULER_RESULT_DIR=str(folder))
        if 'cli' in spec:
            env.update(SCHEDULER_STATE=spec['state'], SCHEDULER_CONFIG=spec['config'],
                       SCHEDULER_RECIPIENT=spec['recipient'], SCHEDULER_CLI_JSON=json.dumps(spec['cli']))
        try:
            with (folder / "stdout.txt").open("wb") as out, (folder / "stderr.txt").open("wb") as err:
                result = subprocess.run(spec["command"], cwd=spec["repo"], env=env, stdout=out, stderr=err,
                                        input=spec["prompt"].encode())
            code = result.returncode
        except OSError as exc:
            code = 127
            (folder / "stderr.txt").write_text(str(exc))
        atomic_json(folder / "exited.json", dict(attempt=spec["attempt"], code=code, at=time.time()))
        return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
