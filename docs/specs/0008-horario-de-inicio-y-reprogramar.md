# 0008 · El paciente ve solo la hora de inicio y puede reprogramar

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Al paciente le importa **cuándo empieza** su turno, no cuándo termina. Y si el horario no le sirve, tiene que
poder pedir otro hueco sin llamar ni cancelar y volver a reservar.

## Fuera de alcance

- La hora de fin sigue visible para el consultorio y las profesionales (panel y avisos), y en el archivo del
  calendario, que la necesita.
- Reprogramar un turno con seña dentro del plazo de cancelación (ver regla 8).

## Reglas

1. En los emails y en la página del turno el horario se muestra **solo con la hora de inicio**
   ("Horario: 14:00 h"), nunca "14:00 a 15:00".
2. **Al paciente se le avisa de un cambio solo si cambia el día o la hora de inicio.** Si el consultorio
   cambia únicamente la duración (el final), no recibe email, no se borra su confirmación ni se reinicia su
   recordatorio. A la profesional sí se le avisa de cualquier cambio.
3. Los emails que piden confirmar (recordatorio, reserva cercana y reprogramación) traen, además de
   *Confirmar turno* y *No voy a poder ir*, el enlace **Elegir otro horario**. La página del turno ofrece el
   mismo botón *Reprogramar*.
4. La página de reprogramar muestra los **próximos horarios libres online** del mismo profesional, por día,
   con las mismas reglas que la reserva (anticipación mínima, días máximos, un solo sillón).
5. Elegir uno **mueve el turno** (no crea uno nuevo): conserva paciente, motivo y seña, y la duración pasa a
   ser la del horario elegido.
6. Como el paciente eligió el horario nuevo, el turno queda **confirmado** para ese horario; no se le pide
   confirmar de nuevo. Recibe un email con el cambio (con "Antes: …") y la profesional también.
7. Si el horario elegido se ocupó mientras tanto, se le avisa y se vuelve a mostrar la lista.
8. **Con seña pagada** solo se puede reprogramar hasta `CANCELLATION_NOTICE_HOURS` antes (mismo plazo que
   cancelar); sin seña, hasta que empiece el turno. Pasado el plazo la página lo explica y da el teléfono.
9. Reprogramar exige el mismo link del turno que cancelar: no hace falta ninguna cuenta.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Los emails y la página muestran solo la hora de inicio | `test_the_patient_only_sees_the_start_time` |
| 2 | Cambiar solo la duración no avisa al paciente ni borra su confirmación | `test_changing_only_the_duration_does_not_notify_the_patient` |
| 3 | A la profesional sí se le avisa de un cambio de duración | `test_changing_only_the_duration_still_tells_the_professional` |
| 4 | Cambiar la hora de inicio sigue avisando | `test_changing_the_start_still_notifies_the_patient` |
| 5 | El pedido de confirmación trae "Elegir otro horario" | `test_the_request_offers_choosing_another_time` |
| 6 | La página de reprogramar lista horarios libres del profesional | `test_the_reschedule_page_lists_free_slots` |
| 7 | Elegir un horario mueve el turno, lo deja confirmado y avisa a ambos | `test_the_patient_reschedules_to_another_slot` |
| 8 | Un horario ocupado se rechaza y se vuelve a ofrecer | `test_rescheduling_to_a_taken_slot_is_rejected` |
| 9 | Con seña dentro del plazo no se puede reprogramar | `test_rescheduling_with_deposit_respects_the_notice_period` |
| 10 | Un turno cancelado no se reprograma | `test_a_cancelled_appointment_cannot_be_rescheduled` |

## Casos límite y errores

- Hueco ocupado entre que se mostró la lista y se eligió: *"Ese horario ya no está disponible. Elegí otro, por
  favor."*
- Sin horarios libres próximos: *"Por ahora no hay horarios libres online. Llamanos y lo resolvemos."*

## Configuración

No agrega variables: usa las reglas de reserva existentes (`BOOKING_MIN_LEAD_MINUTES`, `BOOKING_MAX_DAYS_AHEAD`,
`CANCELLATION_NOTICE_HOURS`).
