#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refuse hand-editing a git-tracked file inside a remote clone.

WHAT IT COST US, 29 October 2026: three scheduled publishers on the same
host failed at once. We had patched two files directly inside a git clone
that those services share, and left `.bak`-style files beside them. The
clone could no longer pull -- so every publisher that depends on it broke,
AND our own fix could no longer reach it. Circular.

WHY IT DENIES INSTEAD OF WARNING

We already had this written down as a rule. We had quoted that rule, in
writing, three hours before breaking it. A warning hook printed it on
screen while we carried on.

The published guidance on agent instructions says the same thing: rather
than writing many "never do X" rules, run the actual check. A check
cannot be skipped or reinterpreted, and it costs no context.

WHAT IT DENIES, AND ONLY THAT

A command that drops a file into a known git clone, IF that file is
TRACKED in the local repository. The correct move is then: push to the
remote, then pull on the machine.

WHAT IT LETS THROUGH, deliberately broadly:
  - any path outside the configured clones -- a deployed service
    directory is not a git clone, hand-writing there is legitimate;
  - a file that is NOT tracked: a pull will never overwrite it;
  - reads, `git pull`, service restarts.

A guard that blocks the normal case is worse than no guard. When it
cannot measure, it lets the command through.

CONFIGURATION, by environment variable:
  AGENT_GIT_CLONES   colon-separated remote clone paths to protect
                     (default: none -- the hook does nothing until set)
  AGENT_LOCAL_REPO   path to the local repository used to decide whether
                     a file is tracked (default: current directory)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

CLONES = tuple(p for p in os.environ.get("AGENT_GIT_CLONES", "").split(":")
               if p.strip())
REPO = os.environ.get("AGENT_LOCAL_REPO", os.getcwd())

# Gestures that DROP a file somewhere.
#
# A WITNESS CAUGHT A BUG HERE before this shipped: a non-greedy pattern
# anchored on `cp|mv` captured the FIRST path on the line -- the SOURCE
# (`/tmp/x.py`) -- and never looked at the destination. The hook let
# `mv /tmp/x.py <clone>/tracked.py` straight through.
#
# So we no longer try to work out which argument is the destination. We
# collect EVERY absolute path in a command that moves files, and test
# each one. A source path that happens to sit inside a protected clone
# is itself worth stopping.
MOVES = re.compile(r"\b(?:cp|mv|install|tee|dd|scp|rsync)\b", re.I)
ANY_PATH = re.compile(r"(?<![\w.])(/[^\s'\"|;&><]+)")
REDIR = re.compile(r">\s*(/[^\s'\"|;&]+)")


def targets(command: str) -> list:
    out = [m.group(1) for m in REDIR.finditer(command)]
    if MOVES.search(command):
        out += [m.group(1) for m in ANY_PATH.finditer(command)]
    return out


def in_a_clone(path: str):
    for c in CLONES:
        c = c.rstrip("/")
        if path.startswith(c + "/"):
            return c, path[len(c) + 1:]
    return None, None


def is_tracked(relative: str) -> bool:
    """Ask git. Do not infer from the name.

    A file present on disk may be untracked, and that difference is
    exactly what decides. On any error we return False: a guard that
    blocks because it could not measure blocks the normal case.
    """
    try:
        r = subprocess.run(
            ["git", "-C", REPO, "ls-files", "--error-unmatch", relative],
            capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:                                         # noqa: BLE001
        return False


def main() -> int:
    if not CLONES:
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:                                         # noqa: BLE001
        return 0
    cmd = ((payload.get("tool_input") or {}).get("command") or "")
    if not cmd:
        return 0
    if not any(c.rstrip("/") in cmd for c in CLONES):
        return 0

    for path in targets(cmd):
        clone, rel = in_a_clone(path)
        if not clone or not is_tracked(rel):
            continue
        reason = (
            "DENIED -- hand-editing a git-TRACKED file inside a clone.\n"
            "\n"
            "  file  : %s\n"
            "  clone : %s\n"
            "\n"
            "A pull will overwrite this edit, or conflict with it. When\n"
            "several services share the clone, one conflict stops all of\n"
            "them -- and your own fix can no longer reach the machine.\n"
            "\n"
            "WHAT WORKS, in this order:\n"
            "  1. edit the file in %s\n"
            "  2. git add / commit / push\n"
            "  3. on the machine: git -C %s pull --rebase\n"
            "\n"
            "If this file should NOT be tracked, fix the repository --\n"
            "do not work around this guard."
            % (rel, clone, REPO, clone)
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
