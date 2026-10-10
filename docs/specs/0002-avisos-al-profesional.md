# 0002 · Avisos al profesional

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que cada profesional se entere de los turnos que le reservan, cancelan o mueven **sin tener que entrar
al panel**, y que la víspera reciba su agenda del día siguiente. Hasta ahora todos los avisos del sistema
iban solo al paciente: un turno nuevo quedaba en la agenda y nadie le avisaba a quien lo iba a atender.

## Fuera de alcance

- WhatsApp al profesional (los avisos son por email).
- Avisos a recepción o a administración.
- Datos de contacto del paciente en el mensaje (ver regla 9).

## Reglas

1. Los avisos van al **email de la ficha del profesional**. Si no tiene email cargado no se envía nada, y
   eso no es un error: sirve para que un profesional no reciba avisos si no los quiere.
2. **Turno nuevo:** se avisa cuando el turno pasa a ser real para el consultorio: reserva online sin seña,
   turno cargado por el consultorio, serie, seña acreditada, o un turno cancelado que se reactiva.
3. Un turno **esperando seña no avisa**: aún no es un turno. Avisa cuando se paga.
4. Una **serie** de turnos genera un solo mensaje con todas las fechas.
5. **Cancelación:** se avisa cuando se cancela un turno que ya había sido avisado (reservado o confirmado),
   lo cancele el paciente o el consultorio. Si el turno se cancela antes de que haya salido el aviso de
   "turno nuevo", no sale ninguno de los dos: el profesional nunca llegó a enterarse.
6. **Reprogramación:** se avisa con el horario anterior y el nuevo.
7. Confirmar un turno que ya estaba reservado, o marcarlo atendido o ausente, **no** genera aviso.
8. **Resumen diario:** cada día, a partir de la hora configurada (18 h por defecto), se envía a cada
   profesional con email la agenda del día siguiente: turnos reservados o confirmados, por hora. Si no tiene
   turnos mañana no se envía nada. Se envía una sola vez por profesional y por día.
9. El contenido es el mínimo necesario: **nombre del paciente, día, hora y enlace al panel**. No incluye
   DNI, teléfono, email ni motivo de la consulta: esos datos viven en el panel, no en un correo.
10. Los avisos quedan registrados en *Notificaciones* con su tipo, sin paciente asociado, y usan el mismo
    reintento que el resto de los mensajes.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Una reserva online sin seña avisa al profesional | `test_an_online_booking_emails_the_professional` |
| 2 | El aviso no lleva DNI, teléfono ni email del paciente | `test_an_online_booking_emails_the_professional` |
| 3 | Sin email en la ficha no se envía nada y la reserva funciona | `test_a_professional_without_email_gets_no_notices` |
| 4 | Un turno esperando seña no avisa hasta que se paga | `test_an_unpaid_hold_does_not_email_the_professional_until_paid` |
| 5 | Un turno cargado por el consultorio avisa | `test_a_counter_booking_emails_the_professional` |
| 6 | Una serie manda un solo aviso con todas las fechas | `test_a_series_sends_the_professional_a_single_notice` |
| 7 | Cancelar avisa al profesional | `test_cancelling_tells_the_professional` |
| 8 | Cancelar antes de que salga el aviso de turno nuevo no manda ninguno | `test_cancelling_before_the_new_booking_notice_goes_out_sends_neither` |
| 9 | Reprogramar avisa con el horario anterior y el nuevo | `test_rescheduling_tells_the_professional_both_times` |
| 10 | Confirmar un turno ya reservado no vuelve a avisar | `test_confirming_a_reserved_appointment_does_not_notify_the_professional` |
| 11 | El resumen lista los turnos de mañana, una vez, a partir de la hora | `test_the_evening_digest_lists_tomorrows_appointments_once` |
| 12 | El resumen no sale antes de la hora, ni sin turnos, ni sin email | `test_the_digest_is_not_sent_early_empty_or_without_email` |
| 13 | El resumen entra en la tarea programada | `test_the_scheduled_job_prepares_the_digests` |
| 14 | Cada tipo de aviso tiene su etiqueta en el panel y cabe en la base | `test_every_notification_type_has_a_label_and_fits_the_column` |
| 15 | Los flujos del panel (cargar, mover, cancelar, reactivar, confirmar) avisan lo que corresponde | `test_the_panel_flows_notify_the_professional` |

## Casos límite

- Si el servidor de correo falla, el aviso se reintenta como cualquier otro.
- Si el profesional cambia de email, los avisos siguientes van al nuevo; los ya enviados no se repiten.
- Un profesional recibe avisos de **sus** turnos únicamente.

## Configuración

| Variable | Por defecto |
| --- | --- |
| `PROFESSIONAL_DIGEST_HOUR` | 18 (hora del consultorio, de 0 a 23) |

No hay interruptor general: para que un profesional no reciba avisos alcanza con dejar vacío su email.
