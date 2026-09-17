SHELL := /bin/bash
TF_DIR := infra/terraform

.PHONY: help install dev dev-down migrate seed run test test-pg lint scheduled prod-check backup tf-fmt tf-validate

help:
	@echo "Targets disponibles:"
	@echo "  install      -> instalar dependencias de desarrollo"
	@echo "  dev          -> levantar todo con Docker Compose (app + PostgreSQL + MailHog)"
	@echo "  dev-down     -> bajar servicios docker"
	@echo "  migrate      -> aplicar migraciones"
	@echo "  seed         -> cargar datos demo"
	@echo "  run          -> levantar app local con recarga"
	@echo "  test         -> tests sobre SQLite"
	@echo "  test-pg      -> tests sobre PostgreSQL (TEST_DATABASE_URL=...)"
	@echo "  lint         -> ruff check"
	@echo "  scheduled    -> correr la tarea programada (holds, recordatorios, reintentos)"
	@echo "  prod-check   -> validar configuración y conexión para producción"
	@echo "  backup       -> backup PostgreSQL (pg_dump)"
	@echo "  tf-fmt       -> formatear Terraform"
	@echo "  tf-validate  -> validar Terraform sin credenciales"

install:
	pip install -e ".[dev]"

dev:
	docker compose up --build

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

test-pg:
	@test -n "$(TEST_DATABASE_URL)" || (echo "Definí TEST_DATABASE_URL=postgresql://..." && exit 1)
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) pytest

lint:
	ruff check .

scheduled:
	python -m app.tasks.run_scheduled

prod-check:
	python -m app.tasks.production_check

backup:
	bash ops/pg_backup.sh

tf-fmt:
	terraform -chdir=$(TF_DIR) fmt -recursive

tf-validate:
	terraform -chdir=$(TF_DIR) init -backend=false -input=false >/dev/null && terraform -chdir=$(TF_DIR) validate
