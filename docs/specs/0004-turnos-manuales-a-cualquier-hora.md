# 0004 · Turnos manuales a cualquier hora

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que el consultorio cargue un turno a mano **a la hora y con la duración reales del tratamiento**, sin
depender de la grilla de horarios que se publica para la reserva online. Caso real: la grilla es de
40 minutos (9:00, 9:40, 10:20…) para pacientes nuevos, pero un tratamiento empieza a las 10:00 y dura
1 h 30. Antes había que cargarlo a las 10:20 y después editarlo a las 10:00, y el paciente recibía dos
emails.

Reemplaza las reglas 2 y 6 de la [0003](0003-turnos-largos-cargados-a-mano.md): el horario ya no se
elige de una lista de la grilla.

## Fuera de alcance

- Cargar turnos **fuera** de la disponibilidad del día (sigue pendiente, ver 0003).
- Cambiar cómo reserva online el paciente: elige siempre de la grilla publicada.
- Pisar un turno ya cargado: no se puede ni con confirmación.

## Reglas

1. El formulario de turno manual pide **día, hora de inicio libre (de a 5 minutos) y duración**. La hora
   no tiene que coincidir con la grilla.
2. El turno tiene que quedar **dentro de la disponibilidad** de ese día. Los bloques que se tocan
   cuentan como uno solo (0003, regla 4).
3. Un turno cargado a mano **ocupa todo su rango**. Los horarios libres de la grilla que se superponen
   desaparecen de la reserva online.
4. Después de un turno que termina fuera de la grilla, **la grilla online arranca donde ese turno
   termina**. Con una grilla de 40 minutos desde las 9:00 y un turno de 10:00 a 11:30, el primer
   horario libre online después de ese turno es el de las 11:30 (no las 11:40). No se pierde tiempo
   muerto.
5. **Nunca se pisa un turno ya cargado.** Si el horario elegido se superpone con otro turno, no se
   guarda y se avisa cuál es: *"Atención, tenés un turno a las 11:00 (hasta 11:40). Acortá este turno
   para que termine a las 11:00 o elegí otro horario."* Solo se pueden ocupar horarios libres.
6. El aviso aparece **antes de guardar** (el formulario muestra lo ocupado del día y avisa del choque en
   el momento) y el servidor lo vuelve a comprobar al guardar.
7. El paciente recibe **un solo email**, con el horario real, porque el turno se carga directamente a la
   hora correcta.
8. Editar la hora o la duración de un turno sigue las mismas reglas 2, 3 y 5.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Se carga un turno a una hora fuera de la grilla, con su duración, en un solo paso | `test_a_manual_appointment_can_start_off_the_grid` |
| 2 | El paciente recibe un solo email con el horario real | `test_a_manual_appointment_off_the_grid_sends_a_single_email` |
| 3 | Lo que cubre el turno manual desaparece de la reserva online y el siguiente horario libre arranca donde termina | `test_the_online_grid_restarts_after_a_manual_appointment` |
| 4 | El paciente online puede reservar ese horario que arranca donde terminó el manual | `test_a_patient_can_book_the_slot_that_starts_where_a_manual_one_ends` |
| 5 | Si choca con un turno, se rechaza diciendo a qué hora es ese turno | `test_a_manual_appointment_that_overlaps_names_the_appointment_in_the_way` |
| 6 | Acortado para terminar donde empieza el otro, se guarda | `test_a_manual_appointment_shortened_to_end_where_the_next_starts_is_saved` |
| 7 | Sigue sin poder salirse de la disponibilidad | `test_a_manual_appointment_still_has_to_fit_the_availability` |
| 8 | El paciente online sigue viendo el aviso genérico, sin datos de otro turno | `test_an_online_patient_never_sees_who_has_the_slot` |
| 9 | El formulario pide hora libre y muestra lo ocupado del día | `test_the_manual_appointment_form_takes_any_start_time` |
| 10 | La API del día devuelve disponibilidad y ocupados para el formulario | `test_the_day_plan_lists_availability_and_busy_times` |
| 11 | Si empieza en medio de otro turno, el aviso dice cuándo termina ese turno | `test_a_manual_appointment_that_starts_inside_another_says_when_it_ends` |
| 12 | Mover un turno encima de otro da el mismo aviso | `test_moving_an_appointment_onto_another_names_it` |
| 13 | La agenda del día solo la ve el consultorio | `test_the_day_plan_is_for_staff_only` |

## Casos límite y errores

- El turno elegido roza otro por un minuto: se rechaza igual (regla 5).
- Hay dos turnos en el medio: el aviso nombra el primero que pisa.
- El turno empieza en medio de otro (por ejemplo 10:00 con otro de 9:40 a 10:20): *"Atención, tenés un
  turno de 09:40 a 10:20. Empezá este turno a las 10:20 o elegí otro horario."*
- Si el turno manual se cancela, la grilla online vuelve a su lugar original alrededor de los turnos
  que quedan.

## Configuración

No agrega variables. La grilla de cada día sigue siendo la duración de slot de cada bloque de
disponibilidad.
