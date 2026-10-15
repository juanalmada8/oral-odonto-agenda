# 0003 · Turnos largos cargados a mano

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que quien carga un turno desde el panel pueda elegir **cuánto dura**, para cargar tratamientos de una
hora y media, dos horas o más. Antes la duración se fijaba sola al largo de cada horario de la grilla
(30 minutos), no se veía y no se podía cambiar: un trabajo largo no se podía cargar.

## Fuera de alcance

- Cargar turnos **fuera** de la disponibilidad publicada (ver "Decisiones pendientes").
- Que el paciente reserve online un turno largo: la reserva online sigue ofreciendo solo los horarios
  de la grilla.
- Empezar un turno en un horario que no esté en la grilla (por ejemplo, 10:15 con una grilla de 30).

## Reglas

1. El formulario de turno manual tiene un campo **Duración** visible, de 15 minutos a 4 horas. Cada
   profesional arranca con su duración habitual.
2. Al elegir la duración, los horarios que se ofrecen son **solo los donde el turno entra entero**, ya
   terminado: un turno de 2 h no se ofrece a las 11:30 si la disponibilidad termina a las 12:00.
3. No se ofrece ningún horario donde el turno pisaría a otro ya cargado, aunque solo lo roce.
4. Los bloques de disponibilidad que **se tocan** cuentan como uno solo: una mañana cargada de 9 a 11 y
   de 11 a 13 admite un turno de 2 h a las 10:00. Si hay un hueco entre bloques (9 a 11 y 12 a 14), el
   turno no puede cruzarlo.
5. Un turno largo **ocupa todos los horarios que cubre**: mientras dure, el paciente que reserva online
   no los ve.
6. Cambiar la duración vuelve a pedir los horarios, y mientras no se elija uno no se puede guardar.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | El formulario permite elegir la duración | `test_the_manual_appointment_form_lets_you_choose_the_duration` |
| 2 | Se ofrecen solo los inicios donde el turno largo entra entero | `test_availability_can_be_asked_for_a_longer_appointment` |
| 3 | No se ofrecen inicios que pisan otro turno | `test_a_long_appointment_is_only_offered_where_it_does_not_collide` |
| 4 | Un turno largo puede cruzar dos bloques que se tocan | `test_a_long_appointment_can_span_two_blocks_that_touch` |
| 5 | No puede cruzar un hueco de la disponibilidad | `test_a_long_appointment_cannot_cross_a_gap_in_the_availability` |
| 6 | Ocupa todos los horarios que cubre | `test_a_long_manual_appointment_takes_every_slot_it_covers` |

## Decisiones pendientes

Hoy un turno cargado a mano **no puede salirse de la disponibilidad**: si el trabajo termina después de
la hora de cierre, hay que agregar antes un bloque en *Disponibilidad* para ese día. Permitir cargarlo
igual (con una confirmación explícita, para urgencias y sobreturnos) es una decisión del consultorio, no
técnica; no está implementado.
