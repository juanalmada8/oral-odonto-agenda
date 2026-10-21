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

### Security
- **Protección contra eliminación** activada en Cloud SQL (además de la de Terraform).
- **Acceso manual a la base con la cuenta de Google** (autenticación IAM), sin compartir la contraseña de la
  app: permisos de datos pero no de estructura. `ops/grant_db_access.sh` y `docs/DATABASE_ACCESS.md`.
  ADR 0009 registra además por qué no se activan alta disponibilidad ni réplica en otra región.
- **Cambiar una contraseña cierra todas las sesiones abiertas con la anterior.** Antes, una sesión robada
  seguía valiendo hasta vencer (8 horas) aunque se cambiara la contraseña. Cada usuario tiene una versión
  de sesión que viaja en el token (migración `20261006_12`). Quien cambia su propia contraseña sigue
  conectado en ese navegador.
- **Content-Security-Policy** en todas las páginas: solo se ejecutan los scripts del sitio que llevan el
  nonce de esa respuesta, así que un script inyectado no corre aunque se colara un XSS. Verificado en
  navegador recorriendo la reserva y el panel: cero bloqueos ni errores.
- Dependencias con vulnerabilidades publicadas: `starlette` (desde 1.3.1) y `python-multipart` (desde
  0.0.27), que procesa todos los formularios. `pip-audit` pasa a correr en CI.
- **Terraform configuraba `TRUSTED_PROXY_COUNT=2` apenas había un dominio propio**, valor que solo
  corresponde al balanceador de carga. Con el mapeo de dominio gratuito hay un único salto, y con `2` la
  app habría tomado la entrada de `X-Forwarded-For` que manda el propio cliente: un atacante podía
  falsificarla y saltearse los límites de intentos de login y de reservas. Ahora vale `2` solo con
  `custom_domain_mode = "load_balancer"`. No llegó a producción: el dominio aún no estaba activado.
- **Se versionaron por error planes de Terraform (`tfplan`, `tfplan2`) que contenían, en texto plano,
  la contraseña de Cloud SQL, la cadena de conexión y el `SECRET_KEY` de la aplicación**, y el
  repositorio es público. Se rotaron la contraseña de la base (de la que deriva la cadena de conexión) y el `SECRET_KEY`, se redesplegó, se purgó el historial de
  `main` y se dejó de rastrear el archivo. GitHub conserva los commits de pull requests cerrados, así
  que hay que pedirle a soporte que los elimine; las credenciales expuestas ya no funcionan.
- Control en CI que falla si se versiona un plan o estado de Terraform, un `terraform.tfvars` o un
  `.env`, aunque se fuerce con `git add -f`.

### Fixed
- **Nombres en minúscula o todo en mayúscula** (especificación 0007). Pacientes y profesionales cargaban
  "juan martín" o "ALMADA ORTIZ" y así aparecían en el panel y en los emails. Ahora cada nombre y apellido se
  guarda con inicial mayúscula ("Juan Martín", "Almada Ortiz", "María de los Ángeles", "O'Connor-Díaz"),
  respetando lo escrito con mayúsculas a propósito ("McDonald"). La migración `20261021_14` corrige una vez
  los nombres ya cargados (solo datos, sin vuelta atrás).
- **Un solo sillón: dos turnos ya no pueden superponerse aunque sean de profesionales distintos**
  (especificación 0006, ADR 0010). La regla era por profesional, así que se podía cargar a Sabina y a Nazarena
  a la misma hora y, si las dos atendían el mismo día, la reserva online ofrecía el mismo horario a dos
  pacientes. Ahora cualquier turno activo ocupa el sillón: no se puede reservar, cargar, mover ni reactivar
  encima, la grilla online lo descuenta y el formulario manual muestra lo ocupado con el nombre de la otra
  profesional (*"Atención, el sillón está ocupado: Nazarena Almada Ortiz tiene un turno a las 11:00…"*).
  Toda escritura en la agenda bloquea a todos los profesionales para que dos reservas simultáneas no se
  salteen el control, y la **restricción de exclusión de PostgreSQL** pasa a cubrir todo el consultorio
  (migración `20261020_13`, reversible): la base rechaza el choque aunque alguien se saltee la app.
- Un turno que ya había recibido su recordatorio y se movía a otro día **no se volvía a recordar**:
  el recordatorio se buscaba por turno y no por horario. Ahora cada recordatorio queda atado a la hora
  que anuncia.
- **No se podía cargar a mano un turno largo** (especificación 0003). En el formulario de turno manual la
  duración era un campo oculto que se fijaba al largo de cada horario de la grilla (30 minutos): un
  tratamiento de hora y media o dos horas no se podía cargar. Ahora hay un campo **Duración** visible
  (de 15 minutos a 4 horas) y solo se ofrecen los horarios donde el turno entra entero y sin pisar a otro.
- Un turno tenía que caber dentro de **un único** bloque de disponibilidad: una mañana cargada en dos
  pedazos (9 a 11 y 11 a 13) rechazaba un turno de 2 horas a las 10:00. Ahora los bloques que se tocan
  cuentan como uno solo; un hueco entre bloques sigue siendo un límite.
- En *Notificaciones* los avisos de **Reprogramación** y de **Lista de espera** salían con el tipo en
  blanco: faltaban sus etiquetas. Ahora todas salen de un único mapa, y un test impide que un tipo nuevo
  quede sin etiqueta o no entre en la columna de la base (20 caracteres).
- Terraform no podía aplicar cambios al servicio web. Un ajuste hecho el mismo día para silenciar un cambio
  falso en `terraform plan` (el nombre de la revisión) hacía que Cloud Run respondiera 409 en cuanto el
  servicio cambiaba de verdad; se revierte y se documenta por qué no hay que ignorar ese campo. No
  llegó a producción: el apply falló sin tocar el servicio.
- El chequeo de caída no se podía reemplazar al cambiar de dominio (Google exige borrar antes la alerta
  que lo usa); ahora el nuevo se crea antes de destruir el viejo.
- **Con Mercado Pago apagado, una seña cargada en un profesional dejaba la reserva online sin
  salida**: el turno quedaba esperando un pago imposible con el horario bloqueado. Sin pasarela de pago
  ya no se pide seña; el monto se aplica solo al activar los pagos.
- El texto de política y el consentimiento hablaban de "seña" aunque no se cobrara ninguna.
- La lista de espera no validaba DNI ni nombres y creaba una ficha de paciente por cada intento.
- El alta de profesionales aceptaba nombres vacíos o con números, que se publican en `/reservar`.
- La política de privacidad mostraba "escribinos a" con el enlace vacío cuando no había casilla de
  correo configurada; ahora cae al teléfono del consultorio.
- El degradado de la portada se cortaba en monitores anchos (más de 1480 px).
- Los cambios de CSS desplegados entre dos releases no se veían en los navegadores con la hoja en
  caché: la huella de los estáticos salía de la versión de la app y no del contenido
  ([ADR 0005](docs/decisions/0005-huella-de-estaticos.md)). Las fuentes se servían como
  `application/octet-stream`.
- Mulish no era la primera tipografía: en Mac se veía Avenir Next y en el resto otra
  ([ADR 0006](docs/decisions/0006-mulish-como-unica-tipografia.md)).

### Removed
- 12 imágenes de diseño sin uso en `app/static/brand/` (~4 MB) y los respaldos temporales de Terraform.
- **El sistema deja de guardar datos de salud.** Se saca el campo de antecedentes (alergias,
  medicación) de la ficha del paciente y el campo libre del formulario público donde el paciente
  podía escribir esa información. Guardar datos de salud convierte la base en una de *datos
  sensibles* bajo la Ley 25.326, con obligaciones mucho más pesadas; el producto es una agenda de
  turnos, no una historia clínica. Migración `20261001_11` borra la columna.

### Added
- **Buscador de pacientes con alta en el mismo turno** (especificación 0009). En *Crear turno manual* y
  *Turnos en serie* el paciente se busca escribiendo nombre, apellido o DNI (sin importar acentos ni
  mayúsculas), en lugar de un desplegable con todos. *Crear turno manual* suma **+ Paciente nuevo** (DNI,
  nombre, apellido y, opcionales, celular y email): se crea junto con el turno, y si el DNI ya existe se
  reutiliza la ficha. Nueva ruta `GET /api/v1/patients/search`, solo para el consultorio.
- **El paciente puede reprogramar desde su link** (especificación 0008). Los emails que piden confirmar traen
  **Elegir otro horario** (y la página del turno, el mismo botón): muestra los próximos horarios libres online
  del mismo profesional, por día. Elegir uno **mueve el turno** (no crea otro), lo deja confirmado para ese
  horario y avisa al paciente y a la profesional. Mismas reglas que la reserva (anticipación mínima, un solo
  sillón) y mismo plazo que cancelar cuando hay seña.
- **El paciente confirma su turno desde el email** (especificación 0005). El recordatorio de 24 h
  (`REMINDER_HOURS_AHEAD`) pasa a ser el pedido de confirmación: trae el botón *Confirmar turno*, que abre la
  página del turno con un botón *Sí, voy a ir*. Al tocarlo, el turno queda **confirmado** en el panel sin
  que el consultorio haga nada. La confirmación es un segundo toque y no la simple apertura del link
  porque Outlook/Hotmail abren los links de los emails para revisarlos. Si se reserva o se carga con menos
  de 24 h, el email de la reserva ya trae el botón. Si a las 12 h (`PROFESSIONAL_UNCONFIRMED_HOURS`) el
  paciente todavía no confirmó, la profesional recibe un aviso (uno por turno, solo si al paciente se le
  pidió con tiempo). **La app nunca cancela sola.** Cada link confirma un horario: el link es una firma del
  turno y su hora con `SECRET_KEY`, así que si el turno se reprograma el link viejo deja de servir, la
  confirmación anterior se borra y el paciente recibe un pedido nuevo. No requiere migración. Rotar
  `SECRET_KEY` invalida los links de confirmación ya enviados.
- **Turnos manuales a cualquier día y hora, también fuera del horario de atención** (especificación 0004,
  ampliada). El día se elige en un **calendario** (con atajos a los próximos días en que atiende el
  profesional) y el turno se guarda aunque caiga fuera de la disponibilidad o en un día sin horario
  cargado, con un aviso que no bloquea: la disponibilidad limita solo lo que se ofrece online. La hora deja
  de usar el selector del navegador (que en una Mac en inglés mostraba a.m./p.m.): se escribe en 24 h
  ("1015" queda 10:15) o se toca uno de los **horarios libres**, que incluyen la hora en que termina cada
  turno para encadenar sin huecos. Lo mismo en *Editar turno* y *Turnos en serie*, y las tres pantallas
  eligen la duración de la misma lista. Siguen sin permitirse los turnos en el pasado y pisar otro turno;
  la serie sigue salteando las fechas sin atención.
- **Turnos manuales a cualquier hora** (especificación 0004). El formulario del panel pide hora de inicio
  libre (de a 5 minutos) y duración, en lugar de ofrecer solo los horarios de la grilla online: un
  tratamiento de 10:00 a 11:30 con una grilla de 40 minutos se carga en un paso y el paciente recibe un
  solo email (antes se cargaba a las 10:20, se editaba a las 10:00 y llegaban dos). El formulario muestra
  qué horas atiende el profesional ese día y qué ya está ocupado, y avisa antes de guardar si el turno
  pisa otro: *"Atención, tenés un turno a las 11:00 (hasta 11:40). Acortá este turno para que termine a
  las 11:00 o elegí otro horario."* El servidor aplica la misma regla y **nunca pisa un turno ya cargado**;
  al paciente online se le sigue mostrando el mensaje genérico, sin datos de otros turnos. Después de un
  turno que termina fuera de la grilla, **la grilla online arranca donde ese turno termina** (11:30 y no
  11:40), sin tiempo muerto. Nueva ruta `GET /api/v1/availability/day-plan`, solo para el consultorio.
- **Avisos al profesional por email** (especificación 0002). Hasta ahora todos los avisos iban solo al
  paciente: un turno nuevo quedaba en la agenda y quien lo iba a atender no se enteraba. Ahora cada
  profesional recibe, en el email de su ficha: un aviso por cada **turno nuevo** (reserva online, turno
  cargado por el consultorio, serie en un solo mensaje, seña acreditada o turno reactivado), por cada
  **cancelación** y por cada **cambio de horario**, y cada tarde (desde las 18 h,
  `PROFESSIONAL_DIGEST_HOUR`) su **agenda del día siguiente**, solo si tiene turnos. El contenido es el
  mínimo: nombre del paciente, día, hora y enlace al panel, sin DNI, teléfono, email ni motivo. Sin email
  en la ficha no se envía nada. No requiere migración.
- `docs/PRIMEROS_PASOS.md`: guía para el consultorio, sin jerga técnica, para cargar profesionales y horarios,
  probar una reserva como paciente y usar la agenda a diario.
- Correo propio: `turnos@oral.com.ar` recibe con Cloudflare Email Routing y envía con Brevo por SMTP, con SPF,
  DKIM y DMARC en `PASS` verificados con un envío real desde producción. ADR 0008, con el límite de 300
  emails por día y el riesgo de la cabecera de baja que Brevo agrega a todos sus mensajes, más la revisión
  periódica para mitigarlo en `docs/OPERATIONS.md`.
- ADR 0007: titularidad. El repositorio y el proyecto de Google Cloud siguen en las cuentas de quien
  desarrolla y administra; se documenta el riesgo de depender de una sola persona y las medidas pendientes.
- `ops/create_admin.sh`: alta de administradores en producción con la clave por teclado, que siempre
  restaura el job y borra las credenciales de su configuración.
- `AGENTS.md`, `docs/decisions/` (6 decisiones de arquitectura) y `docs/specs/` (proceso, plantilla y
  la especificación de la reserva online, con cada criterio atado a su test).
- Página pública **/privacidad**: qué datos se piden y para qué, quién los ve, dónde se guardan,
  cuánto se conservan y cómo ejercer los derechos de acceso, rectificación y supresión.
- Consentimiento explícito al reservar: la casilla ahora cubre el tratamiento de los datos y enlaza
  la política. La lista de espera también la enlaza.
- `odonto-create-admin`: crea el primer usuario administrador a partir de variables de entorno, sin
  cargar datos de demostración. Es idempotente, así que reintentar el job no cambia contraseñas.

### Changed
- **Editar turno: el estado ofrece solo lo que se puede hacer desde el estado actual**, con nombres de acción
  (*Confirmado*, *Atendido*, *Ausente*, *Cancelar el turno*, *Reactivar el turno*). Ya no aparecen "Vencido" ni
  "Pendiente de pago", que los pone el sistema.
- **Al paciente solo se le muestra la hora de inicio** ("Horario: 14:00 h", no "14:00 a 15:00") en emails y en
  la página del turno; la hora de fin sigue en el panel, en los avisos a la profesional y en el calendario.
- **Cambiar solo el final de un turno ya no avisa al paciente**: se le avisa únicamente si cambia el día o la hora
  de inicio. Si cambia solo la duración, tampoco se borra su confirmación ni se reinicia su recordatorio. La
  profesional sí se entera de cualquier cambio.
- **"Confirmar" deja de ser el botón principal del turno** (especificación 0005, regla 10): ahora confirma el
  paciente. Antes de la hora, un turno reservado o confirmado no tiene botón principal (*Confirmar* queda en
  el menú ⋯ por si el paciente llama); desde que empieza, el principal es *Atendido*.
- **El paciente puede avisar que no va desde el email de confirmación** (regla 9): junto a *Confirmar turno*
  hay un enlace *No voy a poder ir* que lleva al botón de cancelar de la página del turno (pide confirmación
  en pantalla). Sin seña pagada se puede cancelar online **hasta que empiece el turno** (antes, hasta 24 h
  antes: justo cuando llega el pedido de confirmación ya era tarde); con seña se mantiene el plazo, porque de
  él depende la política de la seña. La página del turno deja de mostrar el texto de la seña cuando no hay.
- El email de la reserva ya pide confirmar si el turno es dentro de las próximas **26 h** (24 h del
  recordatorio más 2 h de margen). Antes, quien reservaba para mañana a la misma hora recibía dos emails con
  minutos de diferencia: la reserva, y el recordatorio en cuanto se cumplían las 24 h.
- El panel abre en un **Overview**: título *Resumen*, la agenda de hoy (con su filtro de fecha) y una
  sección **Próximos 7 días** con los turnos agrupados por día. Las tarjetas cuentan lo que importa sin
  seña activa (*Sin confirmar* en lugar de *Reservados sin seña*); *Esperando seña* aparece solo si hay alguno.
- Favicon nuevo: el logo de ORAL dentro de un círculo blanco, legible en pestañas claras y oscuras, con
  versiones para celulares (`apple-touch-icon`) y `/favicon.ico`.
- El teléfono del consultorio deja de mostrarse en la portada de reservas. Sigue en los emails, en la
  página del turno y en la política de privacidad.
- Dependencias actualizadas: `actions/checkout` 7, `actions/setup-python` 7, `actions/upload-artifact` 7,
  `google-github-actions/setup-gcloud` 3, `hashicorp/setup-terraform` 4 y el proveedor de Google de Terraform
  8.4. Se verificaron con CI, con un despliegue real a producción y con un `terraform plan` contra la
  infraestructura existente, que dio idéntico al del proveedor anterior.
- Los servicios dejan de llamarse `*Agent` y pasan a `*Service` (`BookingService`, `FollowUpService`,
  `ReceptionService`, `ScheduleService`), con sus archivos en `app/services/`. Eran clases comunes de
  Python, sin IA, pero el nombre sugería lo contrario. Cambio puramente de nombres: verificado con la
  suite completa y el barrido QA de 243 comprobaciones. Las entradas anteriores de este archivo
  conservan los nombres con los que se publicaron.
- El paquete pasa a llamarse `oral-turnos` (antes `odonto-agenda-ai`). Solo cambia el nombre del
  metadato: el código sigue en `app/`.
- Documentación reescrita con el procedimiento real de despliegue: proyecto, estado, infraestructura,
  variables de GitHub, dominio con Cloudflare, rotación de secretos y cómo desplegar una funcionalidad.
  README y CONTRIBUTING reflejan el flujo (especificación, test, PR) y se corrigen datos vencidos
  (región, "historia clínica" en el roadmap, referencias a datos de salud).
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
