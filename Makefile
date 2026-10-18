PY ?= .venv/bin/python

.PHONY: setup data test eval eval-live baseline demo clean

setup:
	python3.12 -m venv .venv
	$(PY) -m pip install -q -e ".[dev]"

data:
	$(PY) -m chronicle.gen

test:
	$(PY) -m pytest -q

# One command: regenerate data if missing, run every eval, apply the regression gate.
eval:
	$(PY) -m chronicle.evals --gate

# Same, plus live Haiku vs Sonnet extraction (needs ANTHROPIC_API_KEY).
eval-live:
	$(PY) -m chronicle.evals --live --gate

# Save the current results as the baseline the gate compares against.
baseline:
	$(PY) -m chronicle.evals --save-baseline

demo:
	$(PY) -m uvicorn chronicle.app:app --port 8000

clean:
	rm -rf data results .pytest_cache
