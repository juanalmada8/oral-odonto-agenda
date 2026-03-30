# Arquitectura

## Visión general

El sistema está dividido en:

- **Web pública** (`/reservar`): reserva autoservicio del paciente.
- **Panel interno** (`/app/*`): operación diaria de recepción/admin.
- **API REST** (`/api/v1/*`): acceso programático y base para integraciones.

## Capas

1. **Presentación**
- `app/web.py` (rutas HTML)
- `app/templates/*`
- `app/static/*`

2. **API**
- `app/api/routes/*`
- `app/api/deps.py`

3. **Dominio / Servicios (agentes)**
- `reception_agent`
- `schedule_agent`
- `followup_agent`
- `professional_service`
- `auth_service`
- `ai_agent` (opcional)

4. **Persistencia**
- SQLAlchemy models en `app/models/*`
- sesión DB en `app/db/session.py`
- migraciones Alembic

## Agentes y responsabilidades

### Reception Agent
- upsert y validación de pacientes por DNI.
- creación/edición/baja lógica de pacientes.

### Schedule Agent
- agenda diaria/semanal.
- disponibilidad por ventana puntual.
- creación/reprogramación/cancelación/completado de turnos.
- control de superposición.

### Followup Agent
- cola de notificaciones.
- confirmaciones inmediatas por email.
- recordatorios de turnos confirmados.
- despacho de pendientes con control de estado.

### Auth Service
- usuarios internos.
- token JWT y control de roles.

### AI Agent (opcional)
- procesamiento de texto libre y asistencia no determinística.
- desacoplado de la lógica clínica/operativa.

## Modelo de datos (resumen)

- `users`
- `patients`
- `professionals`
- `availability_windows`
- `appointments`
- `notifications`
- `audit_logs`

## Reglas de negocio principales

- Paciente único por `DNI`.
- Reserva pública prioritaria.
- Administración manual como flujo secundario.
- Recordatorios solo para turnos `CONFIRMED`.
- Confirmaciones enviadas al momento de confirmar (no por batch).

## Decisiones técnicas

- FastAPI + SQLAlchemy sync para simplicidad de MVP.
- Alembic como única vía para cambios de esquema.
- Servicios por responsabilidad para facilitar mantenimiento y tests.
- UI server-side con Jinja2 para entrega rápida y robusta.

