#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refuse a success line that is not conditioned on anything.

WHAT IT COST US, 29 October 2026 -- three times in one day:

  1. `gh repo fork ... ; echo "branch pushed to the fork"` -- the fork did
     not exist, the push had just failed, and the echo announced success.
     We nearly reported it as fact.
  2. `python patch.py ; echo "syntax verified"` -- the patch had failed on
     an AssertionError. The line printed anyway.
  3. `[ -n "$F" ] && cp ... ; echo "deployed"` -- same shape.

The defect is always the same: an `echo` of success separated from the
command by `;` or a newline runs WHATEVER HAPPENS. It turns a failure
into a success in the transcript -- and the transcript is what a human,
or the next agent, reads.

WHAT IT DENIES
A success word inside an `echo`/`print` that is tied to nothing: no
`&&`, no `if`, no check of the return code.

WHAT IT LETS THROUGH, deliberately broadly:
  - `cmd && echo ok`                 -- tied by &&;
  - `if cmd; then echo ok; fi`       -- conditioned;
  - `echo "ok: $(cmd)"`              -- the value comes from the command;
  - an echo that REPORTS a measurement without claiming success;
  - anything with no success word.

A guard that blocks the normal case is worse than no guard. Two of these
negative cases were found by its own witnesses before it shipped -- one
of them would have blocked half of our commands.
"""
from __future__ import annotations

import json
import re
import sys

# Words that CLAIM success. Stems plus common inflections: "verified"
# escaped a \bverify\b pattern in the first version -- and "verified" was
# the exact word of the false success that motivated this hook.
SUCCESS = re.compile(
    r"\b(ok|done|success|succeeded|passed|fixed|deployed|published|"
    r"pushed|created|installed|verified|complete|completed|"
    r"succes|reussi|termin|fini|deploy|pouss|publi|branch|corrig|"
    r"verifi|install|cree)(e|es|ee|ees|s|d|ed)?\b", re.I)

ECHO = re.compile(r"""(?:^|[;\n&|]|\bthen\b|\bdo\b)\s*
                      (echo|print|printf)\s+
                      (?P<q>["']?)(?P<txt>[^"'\n;]{2,120})(?P=q)""",
                  re.X)


def tied_to_a_result(before: str) -> bool:
    """Is this echo conditioned by what precedes it?"""
    tail = before.rstrip()
    if tail.endswith("&&") or tail.endswith("||"):
        return True
    last = tail.split("\n")[-1]
    if re.search(r"\b(if|then|elif|else|case|while|until)\b\s*$", last):
        return True
    if re.search(r"\$\?|returncode|exit_code", tail[-120:]):
        return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:                                         # noqa: BLE001
        return 0
    cmd = ((payload.get("tool_input") or {}).get("command") or "")
    if not cmd or len(cmd) < 20:
        return 0
    # A single line with no `;` cannot carry this defect.
    if ";" not in cmd and "\n" not in cmd:
        return 0

    for m in ECHO.finditer(cmd):
        txt = m.group("txt")
        if not SUCCESS.search(txt):
            continue
        # A substitution means it REPORTS a measurement, not a claim.
        if "$(" in txt or "`" in txt or "%s" in txt or "{}" in txt:
            continue
        # Up to the `echo` keyword, not the separator: m.start() falls
        # BEFORE a `then`, which made the first version deny a perfectly
        # correct `if cmd; then echo ok; fi`.
        if tied_to_a_result(cmd[:m.start(1)]):
            continue
        reason = (
            "DENIED -- unconditional success line.\n"
            "\n"
            "  found: %s\n"
            "\n"
            "This `echo` runs even if the preceding command fails. It\n"
            "turns a failure into a success in the transcript, which is\n"
            "what a human -- or the next agent -- will read.\n"
            "\n"
            "THREE SHAPES THAT WORK:\n"
            "  cmd && echo \"ok\"\n"
            "  if cmd; then echo \"ok\"; else echo \"FAILED\"; fi\n"
            "  echo \"result: $(cmd)\"   # report instead of claim\n"
            "\n"
            "Or drop the success word and report a MEASUREMENT:\n"
            "  echo \"files: $(ls | wc -l)\"" % txt.strip()[:90]
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
