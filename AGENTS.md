# AGENTS.md

Guía para quien trabaje en este repositorio, sea una persona o una herramienta de programación
asistida. No depende de ninguna herramienta en particular: es Markdown plano. Para el panorama
general leé primero el [README](README.md) y [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Qué es

Plataforma de turnos de **ORAL odontología familiar** (General Belgrano, Buenos Aires): reserva
online para pacientes, panel interno por roles y recordatorios. Python 3.12 · FastAPI · Jinja2 ·
SQLAlchemy 2 + Alembic · PostgreSQL · Docker · Terraform · GitHub Actions · Google Cloud Run.

## Comandos

```bash
pip install -e ".[dev]"      # dependencias
make lint                    # ruff
make test                    # suite sobre SQLite (rápida)
TEST_DATABASE_URL=postgresql+psycopg://... make test-pg   # misma suite sobre PostgreSQL
make run                     # servidor local con recarga (http://localhost:8000)
make migrate                 # alembic upgrade head
```

Antes de dar algo por terminado: `make lint` y `make test` en verde. Si se tocó la base o una
migración, también `make test-pg`. CI repite todo eso y además prueba las migraciones de ida y vuelta.

## Mapa del código

| Carpeta | Contenido |
| --- | --- |
| `app/web/` | páginas HTML: `public.py` (pacientes), `admin.py` (panel), `webhooks.py` |
| `app/api/` | API REST `/api/v1` |
| `app/services/` | reglas de negocio, un servicio por área |
| `app/models/`, `alembic/` | tablas y migraciones |
| `app/integrations/` | Mercado Pago, WhatsApp, SMTP |
| `app/templates/`, `app/static/` | Jinja2 y estáticos (la fuente es Mulish) |
| `tests/` | pytest; nunca leen el `.env` |
| `infra/terraform/`, `ops/` | infraestructura y scripts de operación |
| `docs/` | arquitectura, operación, decisiones (`decisions/`) y especificaciones (`specs/`) |

## Reglas que no se negocian

1. **Este repositorio es público.** Ningún secreto, `.env`, `terraform.tfvars`, estado ni plan de
   Terraform (`tfplan*`) se versiona. CI falla si aparece alguno. Los planes traen las credenciales
   en texto plano: guardalos fuera del repo.
2. **No se guardan datos de salud.** La ficha del paciente es administrativa (ver
   [ADR 0002](docs/decisions/0002-sin-datos-de-salud.md)). No agregar campos clínicos.
3. **Todo cambio de modelo lleva su migración**, reversible, y se prueba sobre PostgreSQL.
4. **Toda fecha u hora de negocio sale de `app.core.clock`**, nunca de `datetime.now()`.
5. **La base de datos es PostgreSQL.** La protección contra turnos superpuestos es una restricción
   de exclusión que SQLite no tiene (ver [ADR 0001](docs/decisions/0001-postgresql.md)).
6. **Un cambio de comportamiento empieza por su especificación** y termina con un test que la
   cubre. Los arreglos de bugs llevan un test que falla sin el arreglo.

## Acciones que requieren confirmación explícita de una persona

No ejecutar por cuenta propia: `terraform apply`/`destroy`, `git push --force`, borrar ramas
remotas, reescribir historial, rotar o escribir secretos, tocar datos de producción, desplegar.
Un `terraform plan` se puede correr y revisar, pero se aplica solo con el visto bueno de quien
responde por la infraestructura.

## Convenciones

- Texto que ve el paciente o el consultorio: **español rioplatense**, claro y sin jerga técnica.
- Identificadores de código en inglés. Comentarios y tests: el idioma del archivo donde se escribe.
- Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `ci:`.
- Ramas cortas y un cambio por pull request. Nada va directo a `main`.
- Cada PR anota su cambio en `CHANGELOG.md` bajo `[Unreleased]`.
- Cambios visuales: comprobarlos en un navegador a escritorio y a celular antes de proponerlos.

## Cómo se trabaja un cambio

1. Redactar o ajustar la especificación en `docs/specs/` (plantilla incluida).
2. Escribir el test que la expresa y verlo fallar.
3. Implementar lo mínimo que lo hace pasar; `make lint` y `make test`.
4. Abrir un pull request con la plantilla; esperar a CI.
5. Mergear y desplegar según [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Dónde está cada cosa

| Pregunta | Documento |
| --- | --- |
| ¿Cómo está armado? | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| ¿Por qué se decidió así? | [docs/decisions/](docs/decisions/) |
| ¿Qué debe hacer, exactamente? | [docs/specs/](docs/specs/) |
| ¿Cómo se despliega o se opera? | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| ¿Qué configuración exige producción? | [docs/PROD_ENV_CHECKLIST.md](docs/PROD_ENV_CHECKLIST.md) |
