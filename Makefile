PYTHON ?= python
PORT ?= 8000

.PHONY: demo install data run serve test

## One command: install pinned deps, generate data, run v1 + v2, start the UI on :8000
demo: install
	$(PYTHON) -m vobeval demo --port $(PORT)

install:
	$(PYTHON) -m pip install -q -r requirements.txt

data:
	$(PYTHON) scripts/generate_data.py

run:
	$(PYTHON) -m vobeval run

serve:
	$(PYTHON) -m vobeval serve --port $(PORT)

test:
	$(PYTHON) -m pytest -q
