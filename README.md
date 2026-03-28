# oral-odonto-agenda

MVP backend para gestion de turnos de un consultorio odontologico, construido con FastAPI, SQLAlchemy, PostgreSQL y Alembic. La logica se organiza como una mini organizacion de agentes internos, pero implementada como servicios simples, mantenibles y desacoplados.

## Arquitectura

- `reception_agent`: recibe solicitudes, valida datos y resuelve alta o busqueda del paciente.
- `schedule_agent`: administra disponibilidad, creacion, reprogramacion y cancelacion de turnos, evitando superposiciones.
- `followup_agent`: prepara confirmaciones y recordatorios, con integracion real para email y un punto de extension para WhatsApp.
- `ai_agent`: modulo opcional desacoplado para interpretar mensajes libres o asistir con respuestas, con fallback si no hay `OPENAI_API_KEY`.
- `auth_service`: maneja usuarios internos, roles y autenticacion JWT simple para admin y recepcion.

## Estructura

```text
odonto-agenda-ai/
├── app/
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── integrations/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── tasks/
│   └── utils/
├── alembic/
├── tests/
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Modelo de datos

- `Patient`: datos del paciente y observaciones.
- `Professional`: odontologos o profesionales del consultorio.
- `AvailabilityWindow`: disponibilidades puntuales por fecha y rango horario para cada profesional.
- `Appointment`: turno con estado, duracion, observaciones y relacion con paciente y profesional.
- `Notification`: cola de notificaciones para confirmaciones y recordatorios.
- `AuditLog`: logs basicos de acciones importantes.

## Requisitos

- Python 3.12+
- Docker y Docker Compose, si queres correr todo containerizado

## Instalacion local

1. Crear entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Copiar variables de entorno:

```bash
cp .env.example .env
```

3. Instalar dependencias:

```bash
pip install -e ".[dev]"
```

4. Levantar PostgreSQL y MailHog con Docker:

```bash
docker compose up -d db mailhog
```

5. Ejecutar migraciones:

```bash
alembic upgrade head
```

6. Iniciar la API:

```bash
uvicorn app.main:app --reload
```

7. Cargar datos demo:

```bash
python -m app.tasks.seed_demo
```

8. Abrir Swagger o la UI:

```text
http://localhost:8000/docs
http://localhost:8000/app/login
```

Credenciales demo:

- `admin / demo12345`
- `recepcion / demo12345`

## Modo rapido sin Docker

Si no tenes Docker disponible y queres probar el MVP rapido, podés usar SQLite local:

```bash
cp .env.sqlite.example .env
source .venv/bin/activate
alembic upgrade head
python -m app.tasks.seed_demo
uvicorn app.main:app --reload
```

En este modo:

- la app funciona para pruebas locales
- no necesitás PostgreSQL ni MailHog
- los emails quedan preparados en la cola, pero no se enviarán realmente si `SMTP_HOST` está vacío
- la base SQLite se guarda en `/tmp/odonto_agenda_local.db` para evitar problemas de permisos sobre la carpeta del proyecto

## Ejecucion con Docker

```bash
cp .env.example .env
docker compose up --build
```

Servicios disponibles:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- MailHog UI: `http://localhost:8025`

## Migraciones

Crear una nueva migracion:

```bash
alembic revision -m "descripcion"
```

Aplicar migraciones:

```bash
alembic upgrade head
```

## Testing

Ejecutar tests:

```bash
pytest
```

Los tests cubren:

- login y acceso autenticado
- alta de pacientes
- creacion de turnos
- validacion de superposicion de horarios

## UI minima

La app ahora incluye una interfaz web ligera para probar el flujo operativo sin depender solo de Swagger:

- login en `/app/login`
- dashboard operativo en `/app`
- reserva publica para pacientes en `/reservar`
- navegación separada en `Dashboard`, `Turnos`, `Pacientes`, `Profesionales`, `Configuración`
- agenda del día como módulo principal del dashboard
- gestión manual secundaria de pacientes y turnos fuera de la home
- configuración de agenda profesional y bloqueos en sección propia
- botones para preparar y enviar recordatorios desde configuración

La UI usa la misma logica de negocio que la API, no un flujo paralelo.

## Criterios de negocio aplicados

- La web pública del paciente es el canal principal para reservar turnos.
- El panel admin quedó orientado a operación diaria, no a formularios masivos.
- El identificador principal del paciente es el `DNI`.
- Si un paciente vuelve a reservar con el mismo `DNI`, se reutiliza el registro y no se duplica.

## Autenticacion y roles

La API protege los endpoints principales con JWT Bearer o cookie de sesion web.

Roles iniciales:

- `admin`: configuracion general, profesionales, horarios y operacion completa
- `receptionist`: operacion diaria de pacientes, turnos y seguimiento

Endpoints utiles:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/users` solo admin
- `POST /api/v1/auth/users` solo admin

## Endpoints principales

- `GET/POST/PUT/DELETE /api/v1/patients`
- `GET/POST/PUT/DELETE /api/v1/professionals`
- `GET/POST/PUT /api/v1/appointments`
- `POST /api/v1/appointments/{id}/reschedule`
- `POST /api/v1/appointments/{id}/cancel`
- `POST /api/v1/appointments/{id}/confirm`
- `POST /api/v1/appointments/{id}/complete`
- `GET /api/v1/appointments/daily`
- `GET /api/v1/appointments/weekly`
- `GET /api/v1/availability`
- `GET /api/v1/availability/week`
- `GET/POST/PUT/DELETE /api/v1/availability/windows`
- `GET /api/v1/notifications`
- `POST /api/v1/notifications/prepare-reminders`
- `POST /api/v1/notifications/send-pending`

## IA opcional

El modulo `app/services/ai_agent.py` queda preparado para usar OpenAI solamente en casos donde agregue valor real, por ejemplo:

- interpretar mensajes libres de pacientes
- sugerir respuestas naturales
- resumir observaciones

No se usa IA para validar horarios, evitar superposiciones ni resolver logica deterministica.

## Recordatorios

El flujo de recordatorios funciona asi:

1. al crear un turno, el sistema puede encolar una confirmacion por email
2. el `followup_agent` detecta turnos proximos y crea recordatorios
3. `app/tasks/send_reminders.py` permite correr el procesamiento manual o via cron

## Notas de diseno

- Se priorizo un MVP funcional y escalable, sin CQRS, colas externas ni microservicios innecesarios.
- Los agentes internos son servicios Python bien delimitados, faciles de entender y testear.
- La app usa FastAPI sync y SQLAlchemy sync para mantener el stack simple en esta etapa.
- La integracion de WhatsApp queda preparada, pero sin forzar una dependencia externa todavia.

## Git

No pude crear el repositorio remoto desde aca. Para dejarlo versionado y subirlo despues:

```bash
cd /Users/juanmartin/financejon/odonto-agenda-ai
git init
git add .
git commit -m "Initial commit: odonto agenda ai MVP"
git branch -M main
git remote add origin <TU_REPO_GITHUB>
git push -u origin main
```
