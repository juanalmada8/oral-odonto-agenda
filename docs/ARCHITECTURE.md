# Arquitectura

## Vista general

```
app/
├── web/            páginas server-side: public.py (pacientes), admin.py (panel), webhooks.py
├── api/            API REST /api/v1 (routes + dependencias)
├── services/       reglas de negocio ("agentes")
├── integrations/   proveedores externos: Mercado Pago, WhatsApp Cloud API, SMTP
├── models/         tablas (SQLAlchemy 2)
├── schemas/        validación de entrada/salida (Pydantic 2)
├── core/           config, reloj, errores, rate limit, seguridad, logging
├── tasks/          seed, chequeo de producción, tarea programada, despachador
└── templates/      Jinja2: páginas + emails
```

## Servicios

| Servicio | Responsabilidad |
| --- | --- |
| `BookingAgent` | reserva pública: valida, bloquea el horario, crea el checkout y cancela por pedido del paciente |
| `ScheduleAgent` | disponibilidad, alta de turnos, transiciones de estado y protección del calendario |
| `PaymentService` | seña: checkout, aplicación idempotente de resultados, vencimientos y devoluciones a revisar |
| `FollowUpAgent` | outbox de notificaciones (email + WhatsApp) con reintentos |
| `WhatsAppBot` | respuestas del paciente por WhatsApp (confirmar asistencia, cancelar) |
| `ReceptionAgent` | pacientes; identidad por DNI en la reserva pública |
| `ProfessionalService`, `AuthService` | staff, usuarios, roles y sesiones |
| `AnalyticsService` | métricas: ocupación, conversión de seña, ausentismo, ingresos |

## Estados del turno

```
pending_payment ──paga──► confirmed ──► completed / no_show
      │                      │
      │ vence (20 min)       └──► cancelled
      ▼
   expired
                 reserved (alta del consultorio) ──► confirmed / completed / no_show / cancelled
```

- **Ocupan agenda**: `pending_payment` (mientras el bloqueo no venció), `reserved`, `confirmed`,
  `completed` y `no_show`.
- Las transiciones válidas están en `ALLOWED_TRANSITIONS` (`app/services/schedule_agent.py`) y se
  validan siempre, venga el pedido del panel, de la API o del bot.

## Reglas de negocio

- Paciente único por DNI. Desde la web pública **nunca** se sobrescribe la ficha existente: si el DNI
  ya existe, el apellido tiene que coincidir y solo se completan los datos vacíos. Los datos de
  contacto de esa reserva viven en el turno.
- No se reservan horarios pasados. La reserva online exige anticipación mínima
  (`BOOKING_MIN_LEAD_MINUTES`), no supera `BOOKING_MAX_DAYS_AHEAD` y el horario tiene que coincidir
  exactamente con un turno publicado.
- Un paciente no puede superponer turnos, ni tener dos con el mismo profesional el mismo día, ni más
  de `BOOKING_MAX_ACTIVE_PER_PATIENT` turnos próximos.
- Un paciente paga una seña por vez: al elegir otro horario, el bloqueo anterior se libera.
- El paciente puede cancelar hasta `CANCELLATION_NOTICE_HOURS` antes, desde el link de su turno o
  por WhatsApp.

## Concurrencia y consistencia

1. Cada reserva toma un **lock de la fila del profesional** (`SELECT ... FOR UPDATE`), de modo que
   dos reservas del mismo profesional se serializan.
2. PostgreSQL tiene además una **restricción de exclusión**: dos turnos activos del mismo profesional
   no pueden superponerse, aunque el código fallara. La violación se traduce a un mensaje amable.
3. Los pagos se aplican de forma **idempotente** y una notificación tardía no puede degradar un pago
   aprobado.
4. El envío de notificaciones toma cada fila con `FOR UPDATE SKIP LOCKED`: dos despachadores en
   paralelo nunca mandan el mismo mensaje dos veces.

## Tiempo

Los turnos se guardan como fecha y hora **local del consultorio** (`APP_TIMEZONE`). Todo el negocio
usa `app.core.clock`, nunca el reloj del servidor (que en la nube está en UTC). Los tests congelan
ese reloj.

## Datos

`user` · `patient` · `professional` · `availability_window` · `appointment` · `payment` ·
`notification` · `audit_log` (+ `working_hours` y `holiday_block`, reservados para agenda recurrente
persistente).

Decisiones:

- Los enums se guardan como **VARCHAR con su valor** (`confirmed`), no como enums nativos de
  PostgreSQL: agregar un estado no requiere `ALTER TYPE` ni migraciones frágiles.
- Los montos son `NUMERIC(12,2)`.
- Los turnos tienen un **token público** impredecible para los links del paciente; nunca se expone el id.
- Toda operación relevante deja registro en `audit_log`.

## Entrega

- Una imagen Docker sirve para los tres roles: web, job de migraciones y job programado.
- Cloud Run + Cloud SQL, con Cloud Scheduler disparando la tarea periódica cada 10 minutos.
- Detalle en [DEPLOYMENT.md](DEPLOYMENT.md).
