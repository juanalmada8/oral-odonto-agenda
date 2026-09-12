# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato sigue la idea de [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y versionado semántico.

## Convención de orden

- Este archivo se mantiene en **orden cronológico inverso**.
- Los cambios nuevos se anotan en **`[Unreleased]`**, arriba de todo.
- Al preparar un release (workflow *Preparar release*), `[Unreleased]` pasa a ser la versión nueva y
  esas notas se publican como GitHub Release. Ver [CONTRIBUTING.md](CONTRIBUTING.md).

## [Unreleased]

### Changed
- Identidad visual alineada a las piezas reales de la marca: azul `#005075` (el del logo), verde
  `#006320`, celeste `#d5ecfc`, coral `#ff5e37`, rosa y lima. Antes el azul del sitio no coincidía.
- Tipografías propias servidas desde la app (Anton para títulos grandes, Mulish como reemplazo libre
  de Avenir Next, que solo existe en Mac y iPhone): la web se ve igual en Android y Windows.
- Hero de la reserva: texto principal más marcado, datos reales del consultorio (dirección y
  ubicación configurables) y tarjeta con el logo de la marca, en lugar de frases genéricas.
- Los archivos estáticos se sirven con versión en la URL, así un deploy nuevo no queda con el CSS
  viejo en la caché del navegador.

### Fixed
- La variante blanca del logo tenía fondo negro sólido: se generó una versión transparente y liviana.

## [0.2.0] - 2026-09-11

### Added — Infraestructura, CI/CD y operación
- Infraestructura como código (`infra/terraform`): Cloud Run (web + jobs de migración y tareas),
  Cloud SQL PostgreSQL con backups y point-in-time recovery, Secret Manager, Artifact Registry,
  Cloud Scheduler cada 10 minutos, alerta de caída opcional y dominio propio opcional con balanceador.
- Deploys desde GitHub Actions con Workload Identity (OIDC, sin claves), migraciones antes de publicar
  la revisión nueva y verificación de `/health/ready`.
- Releases por CI: workflow *Preparar release* (versión + CHANGELOG en un PR) y publicación con tag,
  GitHub Release y deploy al mergear.
- CI: lint, tests sobre SQLite y PostgreSQL, migraciones ida y vuelta, build de la imagen Docker con
  prueba de humo y validación de Terraform. Dependabot y plantilla de PR.
- Dockerfile productivo (multi-stage, usuario sin privilegios) y Docker Compose para desarrollo.
- Logs estructurados JSON para Cloud Logging, `/health/ready` con chequeo de base y pool de conexiones
  configurable.
- Documentación nueva: [MERCADOPAGO.md](docs/MERCADOPAGO.md), [WHATSAPP.md](docs/WHATSAPP.md) y
  deploy/operación/backups reescritos para GCP.

### Removed
- `render.yaml` y `.env.sqlite.example` (reemplazados por Terraform + GCP y por `.env.example`).

### Added — Panel: roles, disponibilidad recurrente y métricas
- Rol **profesional**: cada odontólogo entra con su usuario, ve solo su agenda, carga su propia
  disponibilidad y marca sus turnos como atendidos/ausentes.
- Disponibilidad recurrente (días de la semana + rango de fechas) y bloqueo de días por vacaciones que
  respeta los turnos ya tomados.
- Gestión de usuarios (alta, rol, vínculo con profesional, activación, cambio de contraseña) con
  protección para no quedarse sin administradores.
- Páginas nuevas: Pagos (señas a devolver), Métricas (ocupación, conversión de seña, ausentismo,
  cancelaciones, ingresos por profesional, turnos por día) y exportación CSV para Excel.
- Agenda con estados en español, seña y confirmación de asistencia por turno; acciones según rol y
  transición válida; ficha del paciente con historial.
- Correcciones responsive (desbordes horizontales en celulares) verificadas con navegador headless
  en 360/390/768/1024/1440 px.

### Added — Notificaciones y bot de WhatsApp
- Outbox de notificaciones con reintentos (backoff exponencial, `NOTIFICATION_MAX_ATTEMPTS`) y envío en
  segundo plano apenas termina la operación; filas bloqueadas con `SKIP LOCKED` para no duplicar envíos.
- Emails con diseño de marca (HTML + texto plano): confirmación, recordatorio y cancelación.
- Recordatorios por WhatsApp Cloud API (plantilla aprobada con botones *Confirmo asistencia* /
  *Necesito cancelar*) además del email; también para turnos reservados por el staff.
- Bot de WhatsApp (`/webhooks/whatsapp`, firma `X-Hub-Signature-256`): confirma asistencia, cancela con
  doble confirmación respetando `CANCELLATION_NOTICE_HOURS`, ignora números ajenos y reintentos de Meta.
- El paciente puede cancelar desde el link de su turno (misma política de anticipación).
- Tarea programada `odonto-run-scheduled`: vence holds impagos, prepara recordatorios y reintenta envíos.

### Added — Reserva con seña (Mercado Pago)
- La reserva online bloquea el horario (`pending_payment`) y envía al paciente a pagar la seña con
  Checkout Pro; el turno se confirma solo cuando Mercado Pago aprueba el pago (webhook firmado con HMAC
  + consulta a la API, nunca se confía en la notificación). Si la seña no se paga a tiempo
  (`BOOKING_HOLD_MINUTES`, 20 por defecto) el horario se libera.
- Seña configurable por profesional (vacío = `DEPOSIT_DEFAULT_AMOUNT`, 0 = sin seña).
- Página del turno (`/reservar/turno/<token>`) con estado del pago, cuenta regresiva, reintento de pago,
  archivo `.ics` para el calendario y sincronización inmediata al volver de Mercado Pago.
- Pagos aprobados tarde para un horario ya ocupado quedan marcados para devolución (`/api/v1/payments/requires-refund`).
- Simulador de checkout local (`/pagos/simulador/...`) cuando no hay credenciales de Mercado Pago (nunca en producción).
- Nueva página de reserva: pasos, grilla de horarios, resumen con seña, política de cancelación,
  honeypot anti-bots, límite de intentos por IP y conservación de los datos cargados ante errores.
- Límite de intentos de login por IP y usuario; cookie `secure` y cabeceras de seguridad en producción.

### Fixed
- PostgreSQL: la migración inicial fallaba ("type already exists") y los enums se guardaban por nombre
  (`ADMIN`) en columnas que esperaban el valor (`admin`), así que ninguna inserción funcionaba.
  Los enums pasan a VARCHAR con su valor (migración `20260911_04`, que también corrige datos SQLite).
- `DATABASE_URL` con `postgres://`/`postgresql://` (Render, Cloud SQL) ahora usa psycopg 3.
- Zona horaria: "hoy", "ahora" y los recordatorios usan `APP_TIMEZONE` en vez del reloj del servidor (UTC en la nube).
- Ya no se muestran ni aceptan horarios pasados; la reserva online respeta anticipación mínima y máximo de días.
- `seed_demo` buscaba tablas en plural y no registraba todos los modelos.
- Los tests leían el `.env` local y enviaban emails reales por SMTP.
- El formulario público ya no sobrescribe datos de un paciente existente por conocer su DNI.
- Los errores inesperados ya no se muestran crudos en pantalla.

### Added
- Restricción de exclusión en PostgreSQL + bloqueo por profesional: dos reservas simultáneas del mismo horario no pueden confirmarse ambas.
- Estados de turno `pending_payment`, `no_show` y `expired`, con transiciones validadas.
- Validaciones de DNI, nombres y celular (normalizado a formato WhatsApp `+549...`).
- Suite de tests ejecutable también sobre PostgreSQL (`TEST_DATABASE_URL`), con chequeo de desvío modelos↔migraciones.
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
