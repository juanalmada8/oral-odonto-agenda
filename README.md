# ORAL · Odonto Agenda

Plataforma de turnos para consultorio odontológico:

- **Reserva online** (`/reservar`): el paciente elige profesional, día y horario, y **confirma pagando
  una seña** por Mercado Pago. El horario queda bloqueado mientras paga y se libera solo si no paga.
- **Recordatorios**: confirmación por email y recordatorio por **WhatsApp** con botones para confirmar
  asistencia o cancelar.
- **Panel interno** (`/app`): administración, recepción y cada odontólogo con su propio acceso.
- **API REST** (`/api/v1`) documentada en `/docs`.

## Cómo funciona una reserva

```
Paciente elige horario
        │
        ▼
Turno "seña pendiente"  ──20 min sin pagar──►  se libera el horario
        │
        │ paga la seña (Mercado Pago)
        ▼
Webhook firmado ──► se consulta el pago en la API ──► turno CONFIRMADO
        │
        ├─► email de confirmación (+ .ics para el calendario)
        └─► recordatorio por WhatsApp 24 h antes: [Confirmo] [Cancelar]
```

Todo lo que toca la agenda pasa por las mismas validaciones: no se reservan horarios pasados, se
respeta la anticipación mínima, el horario tiene que existir en la disponibilidad publicada, un
paciente no puede tener dos turnos superpuestos y **dos reservas simultáneas del mismo horario nunca
pueden confirmarse las dos** (bloqueo por profesional + restricción de exclusión en PostgreSQL).

## Stack

Python 3.12 · FastAPI · Jinja2 · SQLAlchemy 2 + Alembic · PostgreSQL · Pytest ·
Docker · Terraform · GitHub Actions · Google Cloud Run + Cloud SQL.

## Arranque rápido

### Con Docker (recomendado)

```bash
cp .env.example .env
docker compose up --build            # app + PostgreSQL + MailHog
docker compose run --rm app python -m app.tasks.seed_demo
```

### Sin Docker (SQLite)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # descomentá la línea de SQLite
alembic upgrade head
python -m app.tasks.seed_demo
uvicorn app.main:app --reload
```

| Dónde | URL |
| --- | --- |
| Reserva online | http://localhost:8000/reservar |
| Panel | http://localhost:8000/app/login |
| API | http://localhost:8000/docs |
| Emails de prueba (MailHog) | http://localhost:8025 |

Usuarios demo: `admin`, `recepcion` y `laura` (odontóloga), todos con `demo12345`.
Sin credenciales de Mercado Pago, el pago de la seña usa un **simulador local** con botones de
aprobar y rechazar.

## Comandos

```bash
make test          # tests sobre SQLite
TEST_DATABASE_URL=postgresql+psycopg://... make test-pg   # misma suite sobre PostgreSQL
make lint          # ruff
make migrate       # alembic upgrade head
make seed          # datos demo
make scheduled     # vencer señas impagas, preparar recordatorios y reintentar envíos
make prod-check    # validar configuración de producción
make tf-validate   # validar Terraform
```

## Roles del panel

| Rol | Puede |
| --- | --- |
| **Administración** | todo: turnos, pacientes, profesionales, disponibilidad, pagos, notificaciones, métricas y usuarios |
| **Recepción** | agenda del día, turnos manuales y pacientes |
| **Profesional** | su propia agenda y su disponibilidad; marcar turnos como atendidos o ausentes |

## Documentación

| Documento | Contenido |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | módulos, modelo de datos y reglas de negocio |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | infraestructura en GCP, CI/CD y releases |
| [docs/MERCADOPAGO.md](docs/MERCADOPAGO.md) | seña: configuración, pruebas y devoluciones |
| [docs/WHATSAPP.md](docs/WHATSAPP.md) | bot de WhatsApp: app de Meta, plantilla y webhook |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | día a día del consultorio y resolución de problemas |
| [docs/BACKUPS.md](docs/BACKUPS.md) | backups y restauración |
| [CONTRIBUTING.md](CONTRIBUTING.md) | flujo de trabajo y releases |
| [CHANGELOG.md](CHANGELOG.md) | historial de cambios |

## Estado

Incluye: reserva online con seña, agenda con disponibilidad por profesional (puntual o recurrente),
estados de turno completos (incluye ausentes), notificaciones con reintentos, bot de WhatsApp,
panel por roles, métricas con exportación a CSV, e infraestructura y deploys automatizados.

Roadmap: pagos del total de la consulta, multi-sede, historia clínica y reprogramación
self-service desde el link del turno.
