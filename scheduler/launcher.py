"""Operator-approved executor profiles; selection lives in shared config, not Tasks."""
import argparse
import subprocess
import sys

PROFILES = {
    "claude": ["claude", "--print", "--dangerously-skip-permissions"],
    "codex": ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"],
    "qwen": ["qwen", "--yolo"],
    "kiro": ["kiro-cli", "chat", "--no-interactive", "--trust-all-tools"],
}


def command(executor, model=None):
    result = list(PROFILES[executor])
    if executor == "kiro" and model not in (None, "claude-opus-5.5"):
        raise ValueError("Kiro model is pinned to claude-opus-5.5 by operator policy")
    model = model or ("claude-opus-5.5" if executor == "kiro" else None)
    if model:
        result += ["--model", model]
    # No effort flag: preserve each CLI's configured default.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", choices=PROFILES, required=True)
    parser.add_argument("--model")
    parser.add_argument("--executable", help="absolute CLI path resolved by the scheduler")
    args = parser.parse_args()
    prompt = sys.stdin.read()
    if not prompt.strip():
        parser.error("worker prompt is required on stdin")
    argv = command(args.executor, args.model)
    if args.executable:
        argv[0] = args.executable
    return subprocess.run(argv + [prompt], stdin=subprocess.DEVNULL).returncode


if __name__ == "__main__":
    raise SystemExit(main())
