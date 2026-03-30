SHELL := /bin/bash

.PHONY: help install dev-up dev-down migrate seed run test lint format reminders

help:
	@echo "Targets disponibles:"
	@echo "  install    -> instalar dependencias de desarrollo"
	@echo "  dev-up     -> levantar db + mailhog"
	@echo "  dev-down   -> bajar servicios docker"
	@echo "  migrate    -> aplicar migraciones"
	@echo "  seed       -> cargar datos demo"
	@echo "  run        -> levantar app local"
	@echo "  test       -> ejecutar tests"
	@echo "  lint       -> ejecutar ruff check"
	@echo "  format     -> ejecutar ruff format"
	@echo "  reminders  -> ejecutar task de despacho"

install:
	pip install -e ".[dev]"

dev-up:
	docker compose up -d db mailhog

dev-down:
	docker compose down

migrate:
	alembic upgrade head

seed:
	python -m app.tasks.seed_demo

run:
	uvicorn app.main:app --reload

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

reminders:
	python -m app.tasks.send_reminders

