# Polybot Code Review

## Scope
Reviewed the source packaged in `polymarket-binary-arb-bot.zip` with focus on runtime safety, robustness, and testability.

## Key Findings

### 1) Test suite fails to import package by default (high)
- Running `pytest -q` directly fails during test collection with:
  - `ModuleNotFoundError: No module named 'src'`
- This indicates tests currently depend on callers manually setting `PYTHONPATH` or running from a specific shell context.
- Recommendation:
  - Add a `pytest.ini` with `pythonpath = .` or package/install the project in editable mode for tests.

### 2) Potential runtime crash in market discovery logging (high)
- In `src/gamma_client.py`, success logging slices token IDs (`[:12]`) without fully guarding for missing IDs.
- If Gamma returns malformed/partial token arrays, that debug/info logging path can throw and mask an otherwise recoverable response.
- Recommendation:
  - Guard with a helper like `(token or "None")[:12]` before slicing.

### 3) Paper/live mode safety model is good but still allows ambiguous config states (medium)
- `load_config()` force-downgrades `live` mode unless `LIVE_TRADING=true`, which is good.
- However, user messaging is `print()`-based and mode intent (`mode_explicitly_set`) can become hard to reason about for downstream components.
- Recommendation:
  - Route safety messages through structured logging and explicitly annotate final effective mode + reason in one place.

### 4) Several broad `except Exception` blocks make failures opaque (medium)
- Multiple modules use broad catches for core IO/data paths.
- This prevents hard crashes, but can hide recurring parse/schema issues and make root-cause analysis harder.
- Recommendation:
  - Narrow exceptions where feasible (`ValueError`, `KeyError`, HTTP/WS errors) and include contextual metadata in logs.

### 5) Repository packaging/developer ergonomics (medium)
- The repo currently ships primarily as a zip artifact rather than a first-class source tree.
- This complicates tooling workflows (linters, type checks, standard CI, code navigation, and PR diffs).
- Recommendation:
  - Commit source as normal files, exclude runtime artifacts (`__pycache__`, logs), and run CI against the unpacked tree.

## Strengths
- Clear modular structure (`bot`, `gamma_client`, `websocket_client`, `risk`, `strategies`).
- Good safety bias toward paper mode.
- Risk manager includes meaningful controls (position limits, stale-data guard, circuit breaker).

## Suggested Next Steps (Priority Order)
1. Fix test import path so `pytest -q` works out of the box.
2. Harden `gamma_client` token-ID logging path.
3. Add lightweight CI (`pytest`, `ruff`, `mypy`/`pyright` optional).
4. Promote code from zip artifact into tracked source files.
