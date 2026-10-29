#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Planted witnesses for both hooks.

Each hook gets cases it MUST deny and cases it MUST NOT touch.

The negative cases are the ones that earn their keep. Two of them caught
real bugs in `no_unconditional_success` before it shipped: "verified"
escaped the pattern by inflection -- the exact word of the false success
that motivated the hook -- and `if cmd; then echo ok; fi` was DENIED,
which would have blocked half of a normal session.

A guard that blocks the normal case is worse than no guard.

Run:  python test_hooks.py        (exit 0 = every witness holds)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run(hook: str, command: str, env: dict | None = None) -> bool:
    """Return True if the hook denied the command."""
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "hooks", hook)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True, text=True, timeout=60, env=e)
    return '"deny"' in (r.stdout or "")


def make_repo() -> tuple:
    """A throwaway repo with one tracked file, and a fake clone path."""
    d = tempfile.mkdtemp(prefix="hooktest-")
    sub = os.path.join(d, "repo")
    os.makedirs(os.path.join(sub, "ops"))
    open(os.path.join(sub, "ops", "tracked.py"), "w").write("x = 1\n")
    for cmd in (["git", "init", "-q"],
                ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t",
                 "commit", "-q", "-m", "base"]):
        subprocess.run(cmd, cwd=sub, capture_output=True)
    return sub, "/srv/clone"


def main() -> int:
    repo, clone = make_repo()
    env = {"AGENT_GIT_CLONES": clone, "AGENT_LOCAL_REPO": repo}
    failures = 0

    cases = [
        # (hook, label, command, must_deny, env)
        ("no_hand_edit_in_clone.py", "DENY scp of a tracked file",
         "scp x.py host:%s/ops/tracked.py" % clone, True, env),
        ("no_hand_edit_in_clone.py", "DENY mv into the clone",
         "sudo mv /tmp/x.py %s/ops/tracked.py" % clone, True, env),
        ("no_hand_edit_in_clone.py", "allow a deployed service path",
         "sudo mv /tmp/x.py /srv/service/app.py", False, env),
        ("no_hand_edit_in_clone.py", "allow an untracked file",
         "sudo mv /tmp/x %s/ops/not_tracked.py" % clone, False, env),
        ("no_hand_edit_in_clone.py", "allow a read",
         "cat %s/ops/tracked.py" % clone, False, env),
        ("no_hand_edit_in_clone.py", "allow git pull",
         "git -C %s pull --rebase" % clone, False, env),
        ("no_hand_edit_in_clone.py", "inert when unconfigured",
         "sudo mv /tmp/x.py %s/ops/tracked.py" % clone, False,
         {"AGENT_GIT_CLONES": "", "AGENT_LOCAL_REPO": repo}),

        ("no_unconditional_success.py", "DENY the real fork case",
         'gh repo fork x\ngit push origin b\necho "branch pushed"',
         True, None),
        ("no_unconditional_success.py", "DENY 'syntax verified'",
         'python patch.py | tail -3\necho "syntax verified"', True, None),
        ("no_unconditional_success.py", "allow && form",
         'python patch.py && echo "ok, applied"', False, None),
        ("no_unconditional_success.py", "allow if/then form",
         'if python p.py; then echo "ok"; else echo "FAILED"; fi',
         False, None),
        ("no_unconditional_success.py", "allow a reported measurement",
         'ls | wc -l\necho "files: $(ls | wc -l)"', False, None),
        ("no_unconditional_success.py", "allow no success word",
         'python x.py\necho "see the output above"', False, None),
        ("no_unconditional_success.py", "allow a single line",
         'echo "deployed"', False, None),
    ]

    for hook, label, cmd, must_deny, e in cases:
        got = run(hook, cmd, e)
        ok = (got == must_deny)
        failures += 0 if ok else 1
        print("  %-4s %-20s %-38s -> %s"
              % ("ok" if ok else "FAIL", hook.replace(".py", "")[:20],
                 label[:38], "DENIED" if got else "allowed"))

    print("  %d witness(es), %d failure(s)" % (len(cases), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
