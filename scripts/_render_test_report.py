#!/usr/bin/env python3
"""Renders test-results/latest.md from pytest/ruff/mypy run output.

Internal helper for scripts/run_tests_with_report.sh — not meant to be
run standalone (though it can be, given the right arguments). Kept as
a separate script rather than inlined in the shell script because
parsing pytest's JUnit XML output is much less error-prone in Python
than in bash/awk.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_junit(junit_path: Path) -> dict:
    """Extracts counts and failure details from a pytest JUnit XML report.

    Returns zeroed-out counts (rather than raising) if the file is
    missing or unparseable, e.g. because pytest crashed before writing
    it (a collection error) — the caller still needs a report either way.
    """
    empty = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "failures": []}
    if not junit_path.exists():
        return empty

    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return empty

    # pytest wraps a single <testsuite> in a <testsuites> root.
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return empty

    total = int(suite.get("tests", 0))
    failed = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    passed = total - failed - errors - skipped

    failures = []
    for testcase in suite.findall("testcase"):
        classname = testcase.get("classname", "")
        name = testcase.get("name", "")
        full_name = f"{classname}::{name}" if classname else name

        for tag_name in ("failure", "error"):
            node = testcase.find(tag_name)
            if node is not None:
                message = (node.get("message") or "").strip().splitlines()[:1]
                message = message[0] if message else ""
                failures.append(f"{full_name} — {message}" if message else full_name)

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "failures": failures,
    }


def status_line(label: str, exit_code: int, detail: str = "") -> str:
    icon = "PASS" if exit_code == 0 else "FAIL"
    suffix = f" — {detail}" if detail else ""
    return f"- **{label}**: {icon} (exit code {exit_code}){suffix}"


def tail(log_path: Path, n_lines: int = 40) -> str:
    if not log_path.exists():
        return "(no output captured)"
    lines = log_path.read_text(errors="replace").splitlines()
    if len(lines) > n_lines:
        lines = [f"... ({len(lines) - n_lines} earlier lines omitted) ..."] + lines[-n_lines:]
    return "\n".join(lines) if lines else "(no output)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--pytest-exit", type=int, required=True)
    parser.add_argument("--pytest-junit", required=True)
    parser.add_argument("--pytest-log", required=True)
    parser.add_argument("--ruff-exit", type=int, required=True)
    parser.add_argument("--ruff-log", required=True)
    parser.add_argument("--mypy-exit", type=int, required=True)
    parser.add_argument("--mypy-log", required=True)
    args = parser.parse_args()

    pytest_stats = parse_junit(Path(args.pytest_junit))
    overall_ok = args.pytest_exit == 0 and args.ruff_exit == 0 and args.mypy_exit == 0

    pytest_detail = (
        f"{pytest_stats['passed']} passed, {pytest_stats['failed']} failed, "
        f"{pytest_stats['errors']} errors, {pytest_stats['skipped']} skipped "
        f"({pytest_stats['total']} total)"
    )

    lines = []
    lines.append("# Test Results")
    lines.append("")
    lines.append(f"**Generated:** {args.timestamp}")
    lines.append(f"**Overall status:** {'PASS' if overall_ok else 'FAIL'}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(status_line("pytest", args.pytest_exit, pytest_detail))
    lines.append(status_line("ruff", args.ruff_exit))
    lines.append(status_line("mypy", args.mypy_exit))
    lines.append("")

    lines.append("## pytest")
    lines.append("")
    lines.append(
        f"{pytest_stats['passed']} passed / {pytest_stats['failed']} failed / "
        f"{pytest_stats['errors']} errors / {pytest_stats['skipped']} skipped "
        f"/ {pytest_stats['total']} total"
    )
    lines.append("")
    if pytest_stats["failures"]:
        lines.append("**Failing tests:**")
        lines.append("")
        for failure in pytest_stats["failures"]:
            lines.append(f"- `{failure}`")
        lines.append("")
    elif args.pytest_exit != 0:
        lines.append("pytest exited non-zero but no individual failing tests were found in the "
                      "JUnit report (likely a collection error) — see the log excerpt below.")
        lines.append("")
        lines.append("```")
        lines.append(tail(Path(args.pytest_log)))
        lines.append("```")
        lines.append("")
    else:
        lines.append("All tests passed.")
        lines.append("")

    lines.append("## ruff")
    lines.append("")
    if args.ruff_exit == 0:
        lines.append("No issues found.")
    else:
        lines.append("```")
        lines.append(tail(Path(args.ruff_log)))
        lines.append("```")
    lines.append("")

    lines.append("## mypy")
    lines.append("")
    if args.mypy_exit == 0:
        lines.append("No issues found.")
    else:
        lines.append("```")
        lines.append(tail(Path(args.mypy_log)))
        lines.append("```")
    lines.append("")

    Path(args.report_file).write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
