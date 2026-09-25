PY ?= python

.PHONY: install validate eval eval-live catalog test check

install:
	$(PY) -m pip install -r requirements.txt

validate:
	$(PY) tools/promptctl.py validate

eval:
	$(PY) tools/promptctl.py eval

eval-live:
	$(PY) tools/promptctl.py eval --live

catalog:
	$(PY) tools/promptctl.py catalog

test:
	$(PY) -m pytest -q

check: test validate eval catalog
