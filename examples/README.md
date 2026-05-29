# Examples

```text
examples/
  tutorial/                 Learn Accentor primitives in order.
  focused_examples/         Runnable capability recipes around one use case.
```

## Start Here

- **New to Accentor:** [tutorial/](tutorial/) — learn primitives step by step
  with mock agents, no live provider needed.
- **Know the primitives, want capabilities:**
  [focused_examples/](focused_examples/) — small, runnable recipes that each
  demonstrate one Accentor capability in a realistic use case.

## What Runs Where

| Layer | Live provider? | Default in pytest? | Purpose |
|-------|----------------|:------------------:|---------|
| Tutorial | Mock default, `--live` opt-in | Yes | Learn primitives step by step |
| Focused examples | Some use `CodexCli` | No | See capabilities in small use cases |

## Setup

Most examples assume Accentor is installed in development mode:

```bash
pip install -e .
```

This removes the need for `sys.path` bootstrapping in individual example files.
If you prefer to run examples from a source checkout without installing, see
the import notes in [focused_examples/README.md](focused_examples/README.md).
