# 0011 · Quién creó cada turno

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que recepción y los profesionales vean, en cada turno del panel, si lo reservó el paciente por la web o lo
cargó alguien del equipo, y quién. Hoy solo dice "Online" o "Consultorio" en la lista de turnos y nada en el
resumen.

## Fuera de alcance

- Que el paciente lo vea: es información interna, no aparece en las páginas públicas ni en los emails.
- Identificar al paciente que reservó online: no hay cuentas de paciente. El turno ya muestra su nombre.
- Filtrar o contar por origen: las métricas ya separan online de consultorio.
- Cambios en la base: se usa el dato `created_by` que ya se guarda en cada turno.

## Reglas

1. Cada turno del panel muestra su origen en la celda **Estado**, como una línea de texto discreta debajo del
   estado. Sin etiquetas de color ni íconos: el panel no decora ([styles.css](../../app/static/styles.css)).
2. Si lo reservó el paciente por la web: **«Reservó el paciente»**.
3. Si lo cargó una persona del equipo: **«Cargó {nombre completo} ({rol})»**, con el rol en minúscula
   (recepción, profesional, administración). El rol va entre paréntesis para que, en el celular, al cortarse la
   línea no quede un signo suelto al final. Vale para turnos sueltos y para series.
4. Si el usuario que lo cargó ya no existe, o el turno viene de una carga técnica (por ejemplo, datos de
   demostración), se muestra **«Cargado en el consultorio»**: nunca un identificador interno.
5. Se muestra en la lista de turnos (`/app/appointments`) y en la agenda de hoy del resumen (`/app`).
6. Un turno que el paciente reprograma desde su link conserva su origen original.
7. Lo ve todo el personal que ya ve el turno; un profesional sigue viendo solo los suyos.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Dado un turno reservado por la web, cuando recepción abre la lista, entonces figura «Reservó el paciente» | `test_online_booking_says_the_patient_booked_it` |
| 2 | Dado un turno cargado por recepción, entonces figura «Cargó {nombre} (recepción)» | `test_manual_appointment_names_who_loaded_it` |
| 3 | Dado un turno cargado por un profesional, entonces figura su nombre y «(profesional)» | `test_a_professional_who_loaded_an_appointment_is_named` |
| 4 | Dado un usuario que ya no existe o una carga técnica, entonces figura «Cargado en el consultorio» y no el identificador | `test_unknown_creator_falls_back_to_the_clinic` |
| 5 | Dado el resumen, entonces la agenda de hoy muestra el origen | `test_dashboard_agenda_shows_the_origin` |
| 6 | Dadas las páginas públicas del turno, entonces no muestran el origen | `test_patient_pages_do_not_show_the_origin` |
| 7 | Dado un nombre con caracteres HTML, entonces se escapa | `test_origin_name_is_escaped` |

## Casos límite y errores

- Si dos usuarios comparten nombre completo, se distinguen por el rol; el nombre de usuario no se muestra.
- Si la persona cambia su nombre completo, los turnos viejos muestran el nombre actual.
