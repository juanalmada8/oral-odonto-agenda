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

### Removed
- **El sistema deja de guardar datos de salud.** Se saca el campo de antecedentes (alergias,
  medicación) de la ficha del paciente y el campo libre del formulario público donde el paciente
  podía escribir esa información. Guardar datos de salud convierte la base en una de *datos
  sensibles* bajo la Ley 25.326, con obligaciones mucho más pesadas; el producto es una agenda de
  turnos, no una historia clínica. Migración `20261001_11` borra la columna.

### Added
- Página pública **/privacidad**: qué datos se piden y para qué, quién los ve, dónde se guardan,
  cuánto se conservan y cómo ejercer los derechos de acceso, rectificación y supresión.
- Consentimiento explícito al reservar: la casilla ahora cubre el tratamiento de los datos y enlaza
  la política. La lista de espera también la enlaza.
- `odonto-create-admin`: crea el primer usuario administrador a partir de variables de entorno, sin
  cargar datos de demostración. Es idempotente, así que reintentar el job no cambia contraseñas.

### Changed
- Dominio propio: se puede usar el **mapeo de Cloud Run, que es gratis**, en lugar del balanceador
  (~USD 18/mes). Como el mapeo no existe en São Paulo, la región por defecto pasa a `us-central1`,
  que además es más barata; Terraform corta con un mensaje claro si se pide mapeo en una región que
  no lo soporta. `custom_domain_mode` permite volver al balanceador.
- Documentación del primer deploy: se crea el admin con `odonto-create-admin` en lugar de correr
  `seed_demo` en producción; los profesionales y su disponibilidad se cargan desde el panel.
- Checklist de producción con el perfil de lanzamiento sin seña y sin WhatsApp (recordatorios por
  email), y cómo sumar Mercado Pago y WhatsApp más adelante sin tocar código.


## [0.2.0] - 2026-09-17

### Added — Agenda del consultorio
- **Lista de espera**: el paciente se anota desde la web (profesional o cualquiera, rango de fechas y
  franja). Cuando un turno se cancela o vence una seña, el horario se ofrece por email a los primeros
  a los que les sirve; nadie queda con el horario reservado. Pantalla en el panel para ver y dar de baja.
- **Turnos en serie** para tratamientos que repiten (ortodoncia, controles): primer turno, cada cuántas
  semanas y cuántos. Las fechas sin lugar se saltean y se informan; el paciente recibe un solo email.
- **Aviso al reprogramar**: si se mueve un turno, el paciente recibe un email con la fecha nueva y la
  anterior. Antes se descartaban los recordatorios pero no se le avisaba.
- **Cobrado en la consulta**: se registra lo que pagó el paciente además de la seña; alimenta la
  métrica "Facturado" (total y por profesional), el CSV y el aviso de atendidos sin cobro cargado.
- **Seña en efectivo** al crear un turno por mostrador, que lo confirma igual que un pago online.
- **Devolución de seña a mano** desde Pagos, para las que se devuelven fuera de Mercado Pago.
- **Ficha del paciente**: nacimiento, domicilio, localidad, obra social y afiliado, contacto de urgencia
  y antecedentes, cargados por el consultorio.

### Changed — Diseño
- Reserva: el formulario pasa a tener profesionales como opciones visibles (con filtros por especialidad
  y "ver todos" cuando son muchos), días en tira, horarios agrupados en mañana y tarde y un resumen
  "Tu turno" fijo al costado. La portada mantiene el logo grande y la tarjeta de marca.
- Panel: sistema visual propio (sin rótulos repetidos, sombras ni degradés), barra lateral agrupada que
  se pliega en el teléfono, una acción principal por turno y el resto en un menú, agenda en tarjetas
  compactas en el teléfono, métricas agrupadas y gráfico de turnos por día con tooltip.
- El azul océano es el color de acción: blanco sobre coral no llega al contraste mínimo de lectura.
- Emails con el logo embebido: Gmail y Outlook bloquean imágenes remotas.
- Paleta tomada de las piezas reales de la marca y Mulish como reemplazo libre de Avenir Next.
- Los archivos estáticos se sirven con versión en la URL para que un deploy no quede con CSS viejo.

### Fixed
- Lista de espera: quien elegía "cualquier profesional" no recibía avisos (`IN` con `NULL`) y quien
  reservaba desde el aviso seguía figurando como "avisado".
- La auditoría fallaba al guardar fechas o importes (columna JSON): editar la seña de un profesional
  rompía el guardado.
- Redirects del panel con 303: con 307 el navegador repetía el POST rechazado.
- La agenda hacía una consulta de pagos por cada turno mostrado.
- El menú de acciones tapaba la fila siguiente y podía disparar la acción del turno equivocado.
- La variante blanca del logo tenía fondo negro sólido.

### Removed
- Módulo de IA sin uso y la dependencia `openai`.


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
