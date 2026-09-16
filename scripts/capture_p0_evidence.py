"""Run the fixed P0 baseline commands and retain their unedited combined output."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "multiuser-rollout" / "evidence" / "P0-R1"

COMMANDS = [
    ("01-npm-ci", ["npm.cmd", "ci"]),
    ("02-npm-test", ["npm.cmd", "test"]),
    ("03-npm-build", ["npm.cmd", "run", "build"]),
    ("04-pytest-collect", [sys.executable, "-m", "pytest", "--collect-only", "-q"]),
    ("05-pytest", [sys.executable, "-m", "pytest", "-q"]),
    ("06-route-audit", [sys.executable, "scripts/audit_routes.py"]),
]


def run(name: str, command: list[str], *, retry: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    begin = time.perf_counter()
    process = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
    )
    duration = time.perf_counter() - begin
    output = process.stdout
    header = {
        "command": subprocess.list2cmdline(command),
        "started_utc": started.isoformat(),
        "duration_seconds": round(duration, 3),
        "exit_code": process.returncode,
        "retry": retry,
    }
    (OUT / f"{name}.log").write_text(
        json.dumps(header, ensure_ascii=False, indent=2) + "\n\n" + output,
        encoding="utf-8",
    )
    return {"name": name, **header, "log": f"{name}.log"}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) == 2 and sys.argv[1] == "--route-retry":
        summary_path = OUT / "SUMMARY.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        result = run(
            "07-route-audit-retry",
            [sys.executable, "scripts/audit_routes.py"],
            retry=True,
        )
        result["retry_of"] = "06-route-audit"
        summary["runs"].append(result)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result["exit_code"]
    if len(sys.argv) == 2 and sys.argv[1] == "--inventory":
        summary_path = OUT / "SUMMARY.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        commands = [
            ("08-python-dependencies", [sys.executable, "-m", "pip", "freeze"]),
            ("09-node-dependencies", ["npm.cmd", "ls", "--depth=0"]),
        ]
        results = [run(name, command) for name, command in commands]
        summary["runs"].extend(results)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if all(item["exit_code"] == 0 for item in results) else 1
    if len(sys.argv) == 2 and sys.argv[1] == "--git-snapshot":
        summary_path = OUT / "SUMMARY.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        commands = [
            ["git", "status", "--short", "--branch"],
            ["git", "diff", "--stat"],
            ["git", "diff", "--name-status"],
            ["git", "diff", "--check"],
        ]
        sections = []
        exit_code = 0
        for command in commands:
            process = subprocess.run(
                command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace"
            )
            exit_code = max(exit_code, process.returncode)
            sections.append(
                "$ " + subprocess.list2cmdline(command) + f"\n[exit {process.returncode}]\n" + process.stdout
            )
        (OUT / "10-git-snapshot.log").write_text("\n\n".join(sections), encoding="utf-8")
        summary["git_snapshot_log"] = "10-git-snapshot.log"
        summary["git_snapshot_exit_code"] = exit_code
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return exit_code
    if len(sys.argv) == 2 and sys.argv[1] == "--route-classification":
        summary_path = OUT / "SUMMARY.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        result = run(
            "11-route-audit-classification",
            [sys.executable, "scripts/audit_routes.py"],
            retry=True,
        )
        result["supersedes"] = "07-route-audit-retry"
        summary["runs"].append(result)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result["exit_code"]
    git = subprocess.run(
        ["git", "status", "--short", "--branch"], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
    ).stdout
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
    ).stdout.strip()
    summary = {
        "evidence_kind": "P0-R1 supplemental rerun; not the original P0 stdout",
        "business_code_sha": "ade703cf20b66cfccc4520730747c0abf07c2158",
        "capture_start_head": head,
        "git_status_before": git,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "node": subprocess.run(["node", "--version"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
            "npm": subprocess.run(["npm.cmd", "--version"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        },
        "test_isolation": "tests/conftest.py creates a fresh temporary MVC_DATA_DIR",
        "paid_egress_guard": "tests use MockTransport/monkeypatch/local test endpoints; no real credentials supplied",
        "runs": [],
    }
    for name, command in COMMANDS:
        result = run(name, command)
        summary["runs"].append(result)
        if result["exit_code"] != 0:
            break
    (OUT / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if len(summary["runs"]) == len(COMMANDS) and all(
        item["exit_code"] == 0 for item in summary["runs"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
