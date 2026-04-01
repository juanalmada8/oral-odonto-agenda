# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato sigue la idea de [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y versionado semántico.

## Convención de orden

- Este archivo se mantiene en **orden cronológico inverso**.
- Los cambios más nuevos van **arriba**.
- Agregá nuevas notas en la primera sección de cambios para que queden en las primeras líneas.

## [Unreleased]

### Added
- Documentación profesional base: `CONTRIBUTING.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`.
- Nueva guía de despliegue productivo: `docs/DEPLOYMENT.md`.
- Checklist de variables de producción: `docs/PROD_ENV_CHECKLIST.md`.
- Guía de backups: `docs/BACKUPS.md`.
- `Makefile` con comandos estándar para dev local.
- Configuración de lint/format con Ruff en `pyproject.toml`.
- Scripts de consola:
  - `odonto-seed-demo`
  - `odonto-send-reminders`
  - `odonto-prod-check`
- Workflow CI para ejecutar tests y lint en pull requests.
- `.env.production.example` para configuración base de producción sobre PostgreSQL.
- `render.yaml` para despliegue inicial en Render (web + PostgreSQL + env base).
- Script operativo `ops/pg_backup.sh` para backup diario con retención.

### Changed
- `README.md` reescrito y alineado al estado real del producto.
- `README.md` ampliado con sección de producción y referencia de deploy.
- `README.md` incluye comando de chequeo preproducción.
- `README.md` incorpora referencias de backup y comando operativo.
- Se eliminó creación automática de tablas al iniciar la app (`app/main.py`): ahora se espera migración con Alembic.
- `seed_demo` valida que el esquema exista antes de cargar datos.
- `Settings` valida seguridad en producción:
  - `SECRET_KEY` obligatoria y robusta.
  - `DATABASE_URL` no puede ser SQLite con `APP_ENV=production`.
- `Makefile` agrega target `prod-check`.
- `Makefile` agrega target `backup`.

### Removed
- Template no usado `app/templates/dashboard.html`.
- Artefactos de build/versionado no deseados `odonto_agenda_ai.egg-info/`.

## [0.1.0] - 2026-03-30

### Added
- MVP funcional de agenda odontológica:
  - reserva pública
  - panel admin/recepción
  - API REST
  - disponibilidad por fecha
  - gestión de pacientes/profesionales/turnos
  - recordatorios por email
