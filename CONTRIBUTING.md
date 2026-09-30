# Contributing

Thanks for your interest in O-Funnel.

## Ground rules

- **Keep it dependency-free.** The library uses only the Python standard library. A new third-party dependency
  needs a strong justification.
- **Test every behavior.** Add or update a test in `tests/` for any change in behavior. The suite must stay
  green.
- **Keep it deterministic.** The same input and requirements must always produce the same output.
- **Adapters are the only format-specific code.** Everything above capture reads the unified tree and stays
  format-blind.

## Setup

```bash
git clone https://github.com/osamaa-mustafa/ofunnel
cd ofunnel
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[test]"
pytest
```

## Adding a new format

Add an adapter in `src/ofunnel/adapters.py` that builds a `Node` tree, register it in `ADAPTERS`, extend
`sniff` if it can be auto-detected, add its origin mapping in `language.py`, and add an oracle branch in
`oracle.py` so captures in the new format are gated. Add round-trip and drop-detection tests.

## Adding a new rung

Rungs live in `src/ofunnel/require.py`. A rung returns candidate matches; fusion in `resolve` combines them.
Keep a rung a witness, not a silent override, and make sure a contradiction lowers confidence rather than being
hidden.

## Style

Small, focused pull requests. Clear names. Docstrings that explain why, not just what.
