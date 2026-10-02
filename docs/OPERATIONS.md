# Operación del día a día

## Qué pasa solo y qué hace falta hacer a mano

| Pasa solo | Cuándo |
| --- | --- |
| Se libera el horario de una seña impaga | al vencer el bloqueo (20 min) |
| Email de confirmación | al acreditarse la seña o al crear un turno desde el panel |
| Recordatorio por email (y por WhatsApp, si está activado) | `REMINDER_HOURS_AHEAD` antes del turno (24 h por defecto) |
| Reintento de un envío que falló | a los 5, 10 y 20 minutos; después queda como *fallida* |
| Email de cancelación | cuando se cancela un turno reservado o confirmado |

Todo eso lo dispara la tarea programada (Cloud Scheduler cada 10 minutos) y, además, cada operación
despacha lo suyo en el momento.

Queda a cargo del consultorio: cargar disponibilidad, atender los avisos del dashboard (señas a
devolver, notificaciones fallidas) y marcar los turnos como **atendido** o **ausente**.

## Rutina sugerida

**Cada mañana (recepción)**

1. `/app` → agenda del día. Con WhatsApp activado, los turnos con ✓ ya confirmaron asistencia.
2. Atender los avisos que aparezcan arriba.
3. Al cerrar el día, marcar atendidos y ausentes (de ahí sale la métrica de ausentismo).

**Cada semana (cada profesional)**

- `/app/availability` → *Repetir cada semana* para dejar cargadas las próximas semanas.
- Vacaciones o congresos: *Bloquear días*. Si algún día tiene turnos tomados, el sistema lo avisa y no
  lo toca hasta que los reprogrames.

**Cada mes (administración)**

- `/app/metrics`: ocupación, conversión de la seña, ausentismo e ingresos. *Exportar CSV* abre en Excel.
- `/app/payments`: señas a devolver.

## Situaciones frecuentes

**El paciente dice que pagó pero el turno figura pendiente.**
`/app/payments` → buscá el pago. Si figura aprobado, el turno se confirma solo al llegar la
notificación; si el horario ya lo tomó otra persona, aparece en *Señas a devolver*.

**El paciente quiere cambiar el horario.**
Recepción: `/app/appointments` → *Editar*. Se valida disponibilidad y se reprograman los
recordatorios. La seña sigue asociada al mismo turno.

**El paciente pide cancelar sobre la hora.**
Online solo puede cancelar hasta `CANCELLATION_NOTICE_HOURS` antes. Después lo hace recepción desde
el panel (queda registrado quién y cuándo).

**Un profesional nuevo.**
`/app/professionals` (alta, duración del turno y seña) → `/app/users` (acceso) →
`/app/availability` (horarios).

**Alguien se olvidó la contraseña.**
`/app/users` → columna *Contraseña* → cambiarla y pasársela por un canal seguro.

**Se perdió la contraseña del único administrador.**
No hay recuperación por email. Desde una computadora con acceso a Google Cloud se crea otro
administrador con un usuario **nuevo** (`ops/create_admin.sh`; con un usuario existente no hace nada)
y desde ahí se cambian las demás claves. Por eso conviene tener siempre **dos** administradores.

## Diagnóstico

| Síntoma | Dónde mirar |
| --- | --- |
| No salen emails | `/app/notifications`: estado SMTP y error de cada mensaje. Sin `SMTP_HOST` y `EMAIL_FROM` configurados no se envía nada |
| No salen WhatsApp | `/app/notifications` + [WHATSAPP.md](WHATSAPP.md) |
| El paciente no ve horarios | `/app/availability`: que haya bloques futuros; la reserva online exige anticipación mínima |
| Falla un pago | [MERCADOPAGO.md](MERCADOPAGO.md) |
| Error inesperado en pantalla | logs: `gcloud run services logs tail oral-web --region ...` |

## Comandos

```bash
make scheduled     # correr la tarea programada a mano
make prod-check    # validar configuración de producción
make migrate       # aplicar migraciones
```

En producción, la tarea programada a mano:

```bash
gcloud run jobs execute oral-scheduled --region us-central1 --wait
```
