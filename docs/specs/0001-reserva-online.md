# 0001 · Reserva online del paciente

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que un paciente reserve un turno desde `/reservar` sin llamar al consultorio, y que el sistema
garantice que dos personas nunca se queden con el mismo horario.

## Fuera de alcance

Reprogramar desde el link (hoy lo hace recepción); pagar el total de la consulta; historia clínica
(ver [ADR 0002](../decisions/0002-sin-datos-de-salud.md)).

## Reglas

1. El paciente elige profesional, día y horario, y completa DNI, nombre, apellido, email y celular
   (el motivo es opcional). Debe aceptar la política y el tratamiento de datos.
2. Solo se ofrecen horarios **publicados** en la disponibilidad del profesional, futuros y libres. El
   horario enviado debe coincidir exactamente con uno publicado.
3. Se exige una anticipación mínima y un máximo de días hacia adelante.
4. Un paciente no puede superponer dos turnos, ni tener dos con el mismo profesional el mismo día, ni
   más de un número fijo de turnos próximos.
5. El paciente se identifica por **DNI**. Si el DNI ya existe, el apellido debe coincidir y la
   reserva **nunca sobrescribe** la ficha: solo completa datos vacíos.
6. Si el profesional requiere seña **y hay pasarela de pago**, el turno queda *pendiente de pago* con
   el horario retenido unos minutos; si no se paga, se libera solo. Si no hay seña, queda
   *reservado* de inmediato. Sin pasarela configurada no se pide seña
   ([ADR 0003](../decisions/0003-lanzamiento-sin-sena-ni-whatsapp.md)).
7. Enviar dos veces el mismo horario reutiliza la reserva; elegir otro libera la retención anterior.
8. El paciente puede cancelar desde el link de su turno hasta cierto tiempo antes.
9. Hay protección contra abuso: campo trampa para bots y límite de intentos por dirección.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Reservar sin seña deja el turno reservado de inmediato | `test_booking_without_deposit_is_reserved_right_away` |
| 2 | Sin pasarela de pago, una seña cargada no bloquea la reserva | `test_without_a_payment_gateway_a_deposit_does_not_block_the_booking` |
| 3 | Con seña, el horario queda retenido y se va al pago | `test_booking_with_deposit_holds_slot_and_sends_patient_to_checkout` |
| 4 | Un pago aprobado confirma el turno | `test_approved_deposit_confirms_the_appointment` |
| 5 | Una retención sin pagar vence y libera el horario | `test_unpaid_hold_expires_and_the_slot_is_released` |
| 6 | Reenviar el mismo horario reutiliza la reserva | `test_resubmitting_the_same_slot_reuses_the_hold` |
| 7 | Elegir otro horario libera la retención previa | `test_choosing_another_slot_releases_the_previous_hold` |
| 8 | Se respeta la anticipación mínima | `test_online_bookings_respect_minimum_lead_time` |
| 9 | Un DNI existente con otro apellido se rechaza | `test_existing_dni_with_another_last_name_is_rejected` |
| 10 | La reserva pública nunca pisa la ficha del paciente | `test_public_booking_never_overwrites_the_patient_record` |
| 11 | Un paciente no acumula turnos próximos sin límite | `test_patients_cannot_hoard_upcoming_appointments` |
| 12 | Un turno por profesional y día | `test_one_appointment_per_professional_and_day` |
| 13 | El campo trampa frena a los bots | `test_honeypot_blocks_bots` |
| 14 | Los intentos están limitados | `test_booking_attempts_are_rate_limited` |
| 15 | La base rechaza turnos superpuestos | `test_database_rejects_overlapping_active_appointments` |
| 16 | Dos reservas simultáneas del mismo horario: gana una sola | `test_concurrent_bookings_of_the_same_slot_only_one_wins` |
| 17 | El paciente cancela desde el link | `test_patient_can_cancel_from_the_booking_link` |
| 18 | El link no deja cancelar dentro del plazo mínimo | `test_cancel_link_is_blocked_inside_the_notice_period` |
| 19 | No se piden datos de salud | `test_la_reserva_publica_no_pide_datos_de_salud` |
| 20 | La política enlazada y publicada | `test_la_politica_de_privacidad_esta_publicada_y_enlazada` |
| 21 | Sin seña, el texto no habla de seña | `test_without_a_deposit_the_policy_does_not_talk_about_one` |

## Casos límite y errores

- Datos inválidos: se explica qué corregir y se conservan los valores ya escritos
  (`test_invalid_data_is_explained_and_typed_values_are_kept`).
- Horario ya tomado: el sistema responde «Ese horario ya no está disponible. Elegí otro, por favor.». La página ofrece además, siempre, anotarse en la lista de espera si ningún horario sirve.
- Un link de turno desconocido muestra una página amable, sin revelar datos
  (`test_unknown_booking_link_shows_a_friendly_page`).

## Configuración

| Variable | Por defecto |
| --- | --- |
| `BOOKING_MIN_LEAD_MINUTES` | 120 |
| `BOOKING_MAX_DAYS_AHEAD` | 60 |
| `BOOKING_MAX_ACTIVE_PER_PATIENT` | 2 |
| `BOOKING_HOLD_MINUTES` | 20 |
| `CANCELLATION_NOTICE_HOURS` | 24 |
| `BOOKING_RATE_LIMIT_PER_HOUR` | 10 |
| `DEPOSIT_DEFAULT_AMOUNT` | 0 (sin seña) |

Los valores por defecto viven en `app/core/config.py`, que es la fuente de verdad.
