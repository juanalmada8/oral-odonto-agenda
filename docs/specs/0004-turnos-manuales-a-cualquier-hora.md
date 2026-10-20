# 0004 · Turnos manuales a cualquier día y hora

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que el consultorio cargue un turno a mano **a la hora y con la duración reales del tratamiento**, sin
depender de la grilla de horarios que se publica para la reserva online. Caso real: la grilla es de
40 minutos (9:00, 9:40, 10:20…) para pacientes nuevos, pero un tratamiento empieza a las 10:00 y dura
1 h 30. Antes había que cargarlo a las 10:20 y después editarlo a las 10:00, y el paciente recibía dos
emails.

La disponibilidad es lo que se ofrece **online**; la agenda es del consultorio. Quien carga a mano decide
el día y la hora, aunque caigan fuera del horario de atención cargado (un sobreturno, una urgencia, un
sábado). Lo único que nunca se permite es pisar otro turno.

Reemplaza las reglas 2 y 6 de la [0003](0003-turnos-largos-cargados-a-mano.md) y resuelve su decisión
pendiente: el horario ya no se elige de una lista de la grilla y puede salirse de la disponibilidad.

## Fuera de alcance

- Cambiar cómo reserva online el paciente: elige siempre de la grilla publicada.
- Pisar un turno ya cargado: no se puede ni con confirmación.
- Cargar turnos en el pasado.
- Turnos en serie: siguen salteando las fechas sin atención (ahí la disponibilidad sirve para detectar
  feriados y vacaciones).
- Que el rol *Profesional* cargue turnos: sigue siendo tarea de administración y recepción.

## Reglas

1. El formulario de turno manual pide **día, hora de inicio libre (de a 5 minutos) y duración**. La hora
   no tiene que coincidir con la grilla.
2. **El día se elige en un calendario**, cualquiera desde hoy, atienda o no ese día. Debajo se sugieren
   los próximos días en que el profesional atiende, para elegirlos con un toque.
3. **La hora va en formato 24 h, sin a.m./p.m.** Se ofrecen como botones los horarios en que el turno
   entra libre dentro del horario de atención (cada 15 minutos) y se puede escribir cualquier otra
   ("1015" queda 10:15).
4. El turno **puede quedar fuera de la disponibilidad** del día: se avisa (*"Queda fuera del horario de
   atención de ese día"*) pero se guarda igual. La disponibilidad solo limita la reserva online.
5. Un turno cargado a mano **ocupa todo su rango**. Los horarios libres de la grilla que se superponen
   desaparecen de la reserva online.
6. Después de un turno que termina fuera de la grilla, **la grilla online arranca donde ese turno
   termina**. Con una grilla de 40 minutos desde las 9:00 y un turno de 10:00 a 11:30, el primer
   horario libre online después de ese turno es el de las 11:30 (no las 11:40). No se pierde tiempo
   muerto.
7. **Nunca se pisa un turno ya cargado.** Si el horario elegido se superpone con otro turno, no se
   guarda y se avisa cuál es: *"Atención, tenés un turno a las 11:00 (hasta 11:40). Acortá este turno
   para que termine a las 11:00 o elegí otro horario."* Solo se pueden ocupar horarios libres.
8. El aviso aparece **antes de guardar** (el formulario muestra lo ocupado del día y avisa del choque en
   el momento) y el servidor lo vuelve a comprobar al guardar.
9. El paciente recibe **un solo email**, con el horario real, porque el turno se carga directamente a la
   hora correcta.
10. Editar el día, la hora o la duración de un turno sigue las mismas reglas: fecha en calendario, hora
    en 24 h, puede salirse de la disponibilidad y nunca pisa otro turno. La serie usa el mismo campo de
    hora.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Se carga un turno a una hora fuera de la grilla, con su duración, en un solo paso | `test_a_manual_appointment_can_start_off_the_grid` |
| 2 | El paciente recibe un solo email con el horario real | `test_a_manual_appointment_off_the_grid_sends_a_single_email` |
| 3 | Lo que cubre el turno manual desaparece de la reserva online y el siguiente horario libre arranca donde termina | `test_the_online_grid_restarts_after_a_manual_appointment` |
| 4 | El paciente online puede reservar ese horario que arranca donde terminó el manual | `test_a_patient_can_book_the_slot_that_starts_where_a_manual_one_ends` |
| 5 | Si choca con un turno, se rechaza diciendo a qué hora es ese turno | `test_a_manual_appointment_that_overlaps_names_the_appointment_in_the_way` |
| 6 | Acortado para terminar donde empieza el otro, se guarda | `test_a_manual_appointment_shortened_to_end_where_the_next_starts_is_saved` |
| 7 | Puede salirse del horario de atención y cargarse un día sin disponibilidad | `test_a_manual_appointment_can_go_outside_the_availability` |
| 8 | El paciente online sigue viendo el aviso genérico, sin datos de otro turno | `test_an_online_patient_never_sees_who_has_the_slot` |
| 9 | El formulario pide hora libre y muestra lo ocupado del día | `test_the_manual_appointment_form_takes_any_start_time` |
| 10 | La API del día devuelve disponibilidad y ocupados para el formulario | `test_the_day_plan_lists_availability_and_busy_times` |
| 11 | Si empieza en medio de otro turno, el aviso dice cuándo termina ese turno | `test_a_manual_appointment_that_starts_inside_another_says_when_it_ends` |
| 12 | Mover un turno encima de otro da el mismo aviso | `test_moving_an_appointment_onto_another_names_it` |
| 13 | La agenda del día solo la ve el consultorio | `test_the_day_plan_is_for_staff_only` |
| 14 | El formulario elige el día en calendario y la hora en 24 h, sin selector a.m./p.m. | `test_the_manual_appointment_form_takes_any_start_time` |
| 15 | Mover un turno fuera de la disponibilidad se guarda | `test_moving_an_appointment_outside_the_availability_is_saved` |
| 16 | Un turno en el pasado se sigue rechazando | `test_a_manual_appointment_in_the_past_is_rejected` |
| 17 | Una hora mal escrita se rechaza con un mensaje claro | `test_a_badly_written_time_is_rejected` |
| 18 | La serie toma fecha y hora 24 h | `test_a_series_takes_date_and_24h_time` |

## Casos límite y errores

- El turno elegido roza otro por un minuto: se rechaza igual (regla 7).
- Hora escrita mal ("25:00", "10.15"): *"Escribí la hora en formato 24 h, por ejemplo 10:15."*
- Un día sin disponibilidad: el formulario dice *"No tiene horario de atención cargado ese día. Igual
  podés cargar el turno."*
- Hay dos turnos en el medio: el aviso nombra el primero que pisa.
- El turno empieza en medio de otro (por ejemplo 10:00 con otro de 9:40 a 10:20): *"Atención, tenés un
  turno de 09:40 a 10:20. Empezá este turno a las 10:20 o elegí otro horario."*
- Si el turno manual se cancela, la grilla online vuelve a su lugar original alrededor de los turnos
  que quedan.

## Configuración

No agrega variables. La grilla de cada día sigue siendo la duración de slot de cada bloque de
disponibilidad.
