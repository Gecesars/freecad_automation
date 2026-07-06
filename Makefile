SHELL := /bin/bash
PY := .venv/bin/python

.venv/bin/python:
	python3 -m venv .venv || python3 -m virtualenv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt

install: .venv/bin/python

run: .venv/bin/python
	. .venv/bin/activate && python -m app.main

ingest: .venv/bin/python
	. .venv/bin/activate && python -m app.rag_ingest_v2

doctor: .venv/bin/python
	. .venv/bin/activate && python -m app.doctor

smoke: .venv/bin/python
	. .venv/bin/activate && python -m app.main --prompt "placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e rasgo central de 40x12 mm" --run-freecad

test: .venv/bin/python
	. .venv/bin/activate && python -m pytest -q

full-test: doctor ingest smoke test

.PHONY: install run ingest doctor smoke test full-test
