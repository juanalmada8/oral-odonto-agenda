# 0005 · Confirmación del turno por el paciente

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que el consultorio no tenga que confirmar los turnos uno por uno. El día antes, el paciente recibe un
email con el botón **Confirmar turno** y lo confirma él mismo. Si a 12 horas del turno todavía no lo
hizo, se le avisa a la profesional. Vale para turnos online y cargados a mano.

## Fuera de alcance

- Cancelar turnos automáticamente: **la app nunca cancela sola** un turno sin confirmar.
- Pedir confirmación a pacientes sin email (el consultorio los confirma por teléfono, como hoy).
- Confirmar por WhatsApp: el bot ya lo permite, pero el canal no está habilitado.

## Reglas

1. **24 horas antes** del turno, el paciente recibe un email con el botón *Confirmar turno*. Es el
   mismo recordatorio de siempre: no se manda un email extra.
2. El botón abre la página del turno con el día y la hora, y un botón *Sí, voy a ir*. Al tocarlo, el
   turno queda **confirmado** en el panel, sin que el consultorio haga nada.
   - La confirmación es un segundo toque y no la simple apertura del link porque los correos
     (Outlook/Hotmail, entre otros) abren los links para revisarlos: si abrir confirmara, quedarían
     confirmados turnos que nadie leyó.
3. Si el turno se reserva o se carga **con menos de 24 horas** de anticipación, el email de la reserva
   ya trae el botón. No se manda otro.
4. A **12 horas** del turno, si el paciente todavía no confirmó, la profesional recibe un email: *"Este
   paciente todavía no confirmó su turno"*. Solo si al paciente se le pidió confirmación por lo menos
   12 horas antes (con menos tiempo no es un aviso útil). Uno por turno y horario.
5. Si el turno ya estaba confirmado (por el consultorio o por una seña pagada), el recordatorio llega
   sin botón y no hay aviso a la profesional.
6. **Cada link confirma un solo horario.** Si el turno se reprograma, la confirmación anterior se borra
   y el turno vuelve a "reservado". El link viejo ya no confirma: muestra el horario nuevo y avisa que
   hay que usar el email nuevo. El paciente recibe un pedido nuevo con su propio link: en el email de
   reprogramación si el turno nuevo es en menos de 24 horas, o en el recordatorio si es más adelante.
7. Si un turno ya recordado se mueve a otro día, se vuelve a recordar para el horario nuevo.
8. Un turno cancelado, vencido o que ya pasó no se puede confirmar.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | El recordatorio de 24 h trae el botón de confirmar | `test_the_24h_reminder_asks_the_patient_to_confirm` |
| 2 | Tocar el link muestra el turno y no confirma solo | `test_opening_the_confirmation_link_does_not_confirm_by_itself` |
| 3 | Confirmar desde la página deja el turno confirmado | `test_the_patient_confirms_from_the_link` |
| 4 | Reservado con menos de 24 h: la confirmación trae el botón y no llega un segundo email | `test_a_booking_inside_24h_asks_for_confirmation_right_away` |
| 5 | A las 12 h sin confirmar, le llega un aviso a la profesional | `test_the_professional_hears_about_an_unconfirmed_patient_at_12h` |
| 6 | Si confirmó, no hay aviso a la profesional | `test_no_alert_once_the_patient_confirmed` |
| 7 | Si nunca se le pidió confirmación con 12 h de margen, no hay aviso | `test_no_alert_when_the_patient_was_asked_too_late` |
| 8 | Un turno ya confirmado recibe el recordatorio sin botón | `test_an_already_confirmed_appointment_gets_a_plain_reminder` |
| 9 | Reprogramado: el link viejo no confirma el horario nuevo | `test_an_old_link_does_not_confirm_a_rescheduled_appointment` |
| 10 | Reprogramado a menos de 24 h: el email de reprogramación trae un link nuevo que sí confirma | `test_a_reschedule_inside_24h_carries_a_new_link` |
| 11 | Reprogramado: se borra la confirmación y vuelve a reservado | `test_rescheduling_clears_the_confirmation` |
| 12 | Recordado y movido a otro día: se vuelve a recordar | `test_a_moved_appointment_is_reminded_again` |
| 13 | Un turno cancelado no se confirma | `test_a_cancelled_appointment_cannot_be_confirmed` |
| 14 | La app nunca cancela un turno sin confirmar | `test_an_unconfirmed_appointment_is_never_cancelled` |
| 15 | Un turno cargado a mano con menos de 24 h también pide confirmación al instante | `test_a_manual_appointment_inside_24h_asks_for_confirmation_right_away` |
| 16 | Si el paciente confirma antes de que salga el aviso, el aviso no se manda | `test_a_queued_alert_is_dropped_if_the_patient_confirms_first` |
| 17 | Un link manipulado no confirma | `test_a_tampered_link_does_not_confirm` |
| 18 | El panel muestra que confirmó el paciente | `test_the_panel_says_the_patient_confirmed` |

## Casos límite y errores

- El paciente toca *Sí, voy a ir* dos veces: la segunda no hace nada y la página muestra que ya está
  confirmado.
- Link viejo después de una reprogramación: *"Este link era para el horario anterior. Tu turno ahora
  es el … Para confirmarlo usá el email más reciente que te mandamos."*
- Link manipulado o incompleto: se muestra la página del turno sin el botón de confirmar.
- El turno ya pasó o fue cancelado: la página lo dice y no ofrece confirmar.

## Configuración

| Variable | Default | Qué hace |
| --- | --- | --- |
| `REMINDER_HOURS_AHEAD` | `24` | Cuándo sale el recordatorio con el pedido de confirmación. |
| `PROFESSIONAL_UNCONFIRMED_HOURS` | `12` | Cuántas horas antes del turno se avisa a la profesional si no confirmó. |
