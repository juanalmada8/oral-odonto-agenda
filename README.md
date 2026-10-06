# ORAL · Turnos

Plataforma de turnos de **ORAL odontología familiar** (Soloeta 443, General Belgrano, Buenos Aires).

- **Reserva online** (`/reservar`): el paciente elige profesional, día y horario y reserva sin llamar.
  Un horario reservado desaparece para los demás y **dos reservas simultáneas nunca pueden quedarse
  con el mismo turno**.
- **Panel interno** (`/app`): administración, recepción y cada profesional con su propio acceso.
- **Avisos por email**: confirmación, recordatorio, reprogramación y cancelación, con reintentos.
- **Lista de espera** y **series de turnos** para tratamientos que se repiten.
- **API REST** (`/api/v1`) documentada en `/docs`.
- **Seña por Mercado Pago** y **bot de WhatsApp**: implementados y probados, **desactivados en el
  lanzamiento** y activables por configuración ([ADR 0003](docs/decisions/0003-lanzamiento-sin-sena-ni-whatsapp.md)).

El sistema es una agenda, **no una historia clínica**: no guarda datos de salud
([ADR 0002](docs/decisions/0002-sin-datos-de-salud.md)).

## Cómo funciona una reserva

```
Paciente elige un horario libre
        │
        ▼
 ¿el profesional pide seña y hay pasarela de pago?
   ├─ no ─► turno RESERVADO ─► email de confirmación
   └─ sí ─► turno "pendiente de pago" (horario retenido 20 min)
              ├─ no paga ─► se libera solo
              └─ paga ─► webhook firmado ─► se consulta el pago ─► CONFIRMADO ─► email
```

Toda reserva pasa por las mismas validaciones: no hay horarios pasados, se respeta la anticipación
mínima, el horario tiene que estar publicado, un paciente no superpone turnos y la base de datos
rechaza dos turnos activos del mismo profesional en el mismo horario. El detalle completo, con la
prueba que respalda cada regla, está en [docs/specs/0001-reserva-online.md](docs/specs/0001-reserva-online.md).

## Stack

Python 3.12 · FastAPI · Jinja2 · SQLAlchemy 2 + Alembic · PostgreSQL 16 · Pytest · Docker ·
Terraform · GitHub Actions · Google Cloud Run + Cloud SQL.

## Arranque local

### Sin Docker (SQLite, lo más simple)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # descomentá la línea de SQLite
alembic upgrade head
python -m app.tasks.seed_demo        # datos de demostración (¡nunca en producción!)
uvicorn app.main:app --reload
```

### Con Docker (PostgreSQL + captura de emails)

```bash
cp .env.example .env
docker compose up --build
docker compose run --rm app python -m app.tasks.seed_demo
```

| Qué | URL |
| --- | --- |
| Reserva online | http://localhost:8000/reservar |
| Panel | http://localhost:8000/app/login |
| API | http://localhost:8000/docs |
| Emails de prueba (solo con Docker) | http://localhost:8025 |

Usuarios de demostración: `admin`, `recepcion` y `laura` (profesional), todos con `demo12345`.
Sin credenciales de Mercado Pago, en desarrollo el pago de la seña usa un **simulador local**.

## Comandos

```bash
make test          # tests sobre SQLite
TEST_DATABASE_URL=postgresql+psycopg://... make test-pg   # misma suite sobre PostgreSQL
make lint          # ruff
make migrate       # alembic upgrade head
make scheduled     # vencer señas, preparar recordatorios y reintentar envíos
make prod-check    # validar configuración de producción
make tf-validate   # validar Terraform sin credenciales
```

## Roles del panel

| Rol | Puede |
| --- | --- |
| **Administración** | todo: turnos, pacientes, profesionales, disponibilidad, pagos, notificaciones, métricas y usuarios |
| **Recepción** | agenda, turnos manuales, pacientes y lista de espera |
| **Profesional** | su propia agenda y disponibilidad; marcar turnos como atendidos o ausentes |

## Documentación

| Documento | Contenido |
| --- | --- |
| [AGENTS.md](AGENTS.md) | guía para quien trabaje en el repo: comandos, reglas y flujo de cambio |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | módulos, modelo de datos y reglas de negocio |
| [docs/decisions/](docs/decisions/) | por qué el sistema es como es (decisiones de arquitectura) |
| [docs/specs/](docs/specs/) | qué debe hacer cada funcionalidad, con el test que lo comprueba |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | infraestructura, despliegues, dominio y rotación de secretos |
| [docs/PRIMEROS_PASOS.md](docs/PRIMEROS_PASOS.md) | guía para el consultorio: cargar profesionales y horarios, y el día a día |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | día a día del consultorio y resolución de problemas |
| [docs/PROD_ENV_CHECKLIST.md](docs/PROD_ENV_CHECKLIST.md) | configuración de producción y cómo activar seña y WhatsApp |
| [docs/BACKUPS.md](docs/BACKUPS.md) | backups y restauración |
| [docs/DATABASE_ACCESS.md](docs/DATABASE_ACCESS.md) | conectarse a la base a mano (DBeaver, psql) con tu cuenta de Google |
| [docs/MERCADOPAGO.md](docs/MERCADOPAGO.md), [docs/WHATSAPP.md](docs/WHATSAPP.md) | integraciones opcionales |
| [CONTRIBUTING.md](CONTRIBUTING.md) | flujo de trabajo, revisión y releases |
| [CHANGELOG.md](CHANGELOG.md) | historial de cambios |

## Fuera de alcance

Historia clínica o cualquier dato de salud (decisión deliberada, ver ADR 0002), multi-sede y pago
del total de la consulta. Agregar algo de esto es un cambio de diseño, no una tarea menor.
