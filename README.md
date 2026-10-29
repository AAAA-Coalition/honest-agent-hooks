# honest-agent-hooks

Two Claude Code `PreToolUse` hooks that **deny** instead of warning.
Python, standard library only, with a witness suite.

They do not block dangerous commands — [other collections already do that
well](https://github.com/karanb192/claude-code-hooks). They block
something else: **an agent quietly lying to itself**.

| hook | denies |
|---|---|
| `no_hand_edit_in_clone` | hand-editing a git-**tracked** file inside a clone another process pulls into |
| `no_unconditional_success` | an `echo "done"` that runs whether or not the command succeeded |

Both were written the evening they cost us something.

---

## Why deny, not warn

We already had both lessons written down. One of them we had quoted, in
writing, **three hours before breaking it**. A warning hook printed it on
screen while the agent carried on.

The published guidance on agent instruction files says the same thing:

> Instead of writing many `never` rules, run the actual checks. Linters,
> type checkers, formatters, tests and CI provide deterministic checks
> that are more reliable than expressing the same constraints only in
> natural-language instructions. **They cannot be skipped or
> misinterpreted, and they do not consume agent context.**

A rule you can read is a rule you can ignore. A denial is not.

---

## 1. `no_hand_edit_in_clone`

**What it cost.** Three scheduled publishers on one host failed at once.
We had patched two files directly inside a git clone those services
share, and left backup files beside them. The clone could no longer pull
— so every publisher broke, **and our own fix could no longer reach the
machine**. Circular.

**What it denies.** A command that drops a file into a configured clone,
*if that file is tracked in your repository*. It asks git; it does not
infer from the name.

**What it lets through**, deliberately broadly:

- any path outside the configured clones — a deployed service directory
  is not a git clone, and hand-writing there is legitimate;
- a file that is **not** tracked: a pull will never overwrite it;
- reads, `git pull`, service restarts;
- everything, when `AGENT_GIT_CLONES` is unset.

## 2. `no_unconditional_success`

**What it cost.** Three false announcements in one day:

```bash
gh repo fork x ; echo "branch pushed to the fork"   # the push had failed
python patch.py ; echo "syntax verified"            # the patch had failed
[ -n "$F" ] && cp … ; echo "deployed"               # same shape
```

A success `echo` separated by `;` or a newline **runs whatever happens**.
It turns a failure into a success in the transcript — and the transcript
is what a human, or the next agent, reads.

**What it lets through**: `cmd && echo ok`, `if cmd; then echo ok; fi`,
`echo "ok: $(cmd)"`, any echo reporting a measurement, anything with no
success word, and any single-line command.

---

## The witnesses earn their keep

```
$ python test_hooks.py
  ok   no_hand_edit_in_clone    DENY scp of a tracked file      -> DENIED
  ok   no_hand_edit_in_clone    allow a deployed service path   -> allowed
  ok   no_unconditional_success DENY 'syntax verified'          -> DENIED
  ok   no_unconditional_success allow if/then form              -> allowed
  …
  14 witness(es), 0 failure(s)
```

**Three real bugs were caught by these witnesses before either hook
shipped:**

1. `verified` escaped the success pattern by inflection — and `verified`
   was the exact word of the false success that motivated the hook.
2. `if cmd; then echo ok; fi` was **denied**, because the check read the
   text before the separator and never saw the `then`. That alone would
   have blocked half of a normal session.
3. The clone hook captured the **source** path of `mv /tmp/x <clone>/f`
   instead of the destination, and let the real case straight through.

The negative cases are the valuable ones. **A guard that blocks the
normal case is worse than no guard**, and only a witness that must *not*
fire will tell you.

---

## Install

```bash
curl -O https://raw.githubusercontent.com/AAAA-Coalition/honest-agent-hooks/main/hooks/no_hand_edit_in_clone.py
curl -O https://raw.githubusercontent.com/AAAA-Coalition/honest-agent-hooks/main/hooks/no_unconditional_success.py
```

In `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "python -S /path/to/no_hand_edit_in_clone.py" },
          { "type": "command", "command": "python -S /path/to/no_unconditional_success.py" }
        ]
      }
    ]
  }
}
```

`no_hand_edit_in_clone` needs two environment variables and **does
nothing without them**:

| variable | meaning |
|---|---|
| `AGENT_GIT_CLONES` | colon-separated clone paths to protect |
| `AGENT_LOCAL_REPO` | the repository used to decide whether a file is tracked |

Python 3.8+. No dependencies.

---

## Limits, stated

**They are regex over a command string.** An agent that really wants to
get around them can. They are there to stop the *absent-minded* version
of the mistake — which, in our experience, is every occurrence of it.

**`no_unconditional_success` only inspects `echo`/`print`/`printf`.** A
success claimed inside a Python script is invisible to it.

**Neither replaces a real check.** They are the cheapest layer of a
[documented spectrum](https://www.openhands.dev/blog/claude-code-best-practices-agentic-coding):
in-prompt check → goal-condition evaluator → stop hook → second-opinion
subagent. If you can afford the last one — a fresh model trying to refute
the result — it is stronger than anything here, because the agent doing
the work is not the one grading it.

---

## Licence

MIT. See [LICENSE](LICENSE).
