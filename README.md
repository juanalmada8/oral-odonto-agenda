# ORAL · Odonto Agenda

Aplicación full-stack para gestión de turnos odontológicos, con:

- web pública de reserva para pacientes (`/reservar`)
- panel interno para administración y recepción (`/app`)
- API REST documentada con FastAPI (`/docs`)

El proyecto está pensado como MVP sólido y escalable, con módulos tipo “agentes” pero sin sobreingeniería.

## Stack

- Python 3.12
- FastAPI + Jinja2
- SQLAlchemy + Alembic
- PostgreSQL (o SQLite para desarrollo local rápido)
- Docker Compose (DB + MailHog)
- Pytest

## Arquitectura resumida

- `reception_agent`: alta/búsqueda/actualización de pacientes.
- `schedule_agent`: disponibilidad, creación y cambios de estado de turnos.
- `followup_agent`: cola y envío de notificaciones (confirmación/recordatorio).
- `auth_service`: autenticación y roles (`admin`, `receptionist`).
- `ai_agent`: extensión opcional para casos de IA no determinísticos.

Más detalle en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Estructura del repositorio

```text
.
├── app/
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── integrations/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── static/
│   ├── tasks/
│   ├── templates/
│   └── web.py
├── alembic/
├── tests/
├── .env.example
├── .env.sqlite.example
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

## Requisitos

- Python 3.12+
- `pip`
- Docker + Docker Compose (recomendado para PostgreSQL/MailHog)

## Quickstart (PostgreSQL + Docker)

1. Crear entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Instalar dependencias:

```bash
pip install -e ".[dev]"
```

3. Configurar variables:

```bash
cp .env.example .env
```

4. Levantar servicios:

```bash
docker compose up -d db mailhog
```

5. Migrar base:

```bash
alembic upgrade head
```

6. Seed demo:

```bash
python -m app.tasks.seed_demo
```

7. Levantar app:

```bash
uvicorn app.main:app --reload
```

## Quickstart rápido (SQLite local)

Ideal para validar UI/flujo sin Docker:

```bash
cp .env.sqlite.example .env
source .venv/bin/activate
alembic upgrade head
python -m app.tasks.seed_demo
uvicorn app.main:app --reload
```

## Accesos

- Reserva pública: `http://localhost:8000/reservar`
- Login interno: `http://localhost:8000/app/login`
- Swagger API: `http://localhost:8000/docs`
- MailHog UI: `http://localhost:8025`

Credenciales demo:

- `admin / demo12345`
- `recepcion / demo12345`

## Variables de entorno

Ver `.env.example` y `.env.sqlite.example`.

Claves principales:

- `DATABASE_URL`
- `SECRET_KEY`
- `SMTP_*` (`HOST`, `PORT`, `USERNAME`, `PASSWORD`, `USE_TLS`)
- `EMAIL_FROM`
- `OPENAI_API_KEY` (opcional)
- `REMINDER_HOURS_AHEAD`

## Notificaciones por email (Gmail)

Si usás Gmail SMTP:

- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=tu_cuenta@gmail.com`
- `SMTP_PASSWORD=<app-password de Google>`
- `SMTP_USE_TLS=true`
- `EMAIL_FROM=tu_cuenta@gmail.com`

Guía operativa completa en [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Comandos útiles

```bash
# migrar
alembic upgrade head

# seed demo
python -m app.tasks.seed_demo

# tests
pytest

# lint
ruff check .

# format (si querés aplicar formato ruff)
ruff format .
```

También podés usar `make` (ver `Makefile`).

## API principal

Base path: `/api/v1`

- Auth: `/auth/*`
- Pacientes: `/patients/*`
- Profesionales: `/professionals/*`
- Turnos: `/appointments/*`
- Disponibilidad: `/availability/*`
- Notificaciones: `/notifications/*`

Swagger actualizado: `GET /docs`.

## Calidad y contribución

- Convenciones de trabajo: [CONTRIBUTING.md](CONTRIBUTING.md)
- Historial de cambios: [CHANGELOG.md](CHANGELOG.md)

## Estado actual del producto

Incluye:

- gestión de turnos y estados clínicos básicos
- agenda por profesional con disponibilidad por fecha/hora
- alta y edición de pacientes/profesionales
- panel de notificaciones con previsualización de envíos
- separación clara entre flujo público y flujo interno

No incluye todavía (roadmap):

- WhatsApp productivo
- multiclínica / multisedes
- reportes de negocio avanzados

