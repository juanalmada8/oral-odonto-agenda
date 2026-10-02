# 0001 · PostgreSQL como única base de producción

**Estado:** vigente · **Fecha:** septiembre de 2026

## Contexto

Dos pacientes pueden elegir el mismo horario en el mismo instante. Evitar el sobreturno no puede
depender solo del código de la aplicación: tiene que estar garantizado por la base.

## Decisión

Producción usa **PostgreSQL 16**. Los turnos activos de un mismo profesional no pueden superponerse,
y eso lo impone una **restricción de exclusión** (`EXCLUDE USING gist` sobre el profesional y el
rango de tiempo, migración `20260911_04`). Además cada reserva toma un lock de la fila del
profesional (`SELECT ... FOR UPDATE`).

SQLite se admite **solo para desarrollo local y tests rápidos**. La aplicación se niega a arrancar
en producción con SQLite.

## Consecuencias

- La misma suite de tests corre sobre SQLite y sobre PostgreSQL; sobre PostgreSQL se aplican las
  migraciones reales y hay un test de concurrencia (`test_concurrent_bookings_of_the_same_slot_only_one_wins`).
- Hay comportamiento que solo se verifica en PostgreSQL. Un test que pasa en SQLite no alcanza.
- Se descartó una base documental o columnar: sin transacciones ni restricciones de exclusión no hay
  forma de garantizar que dos reservas simultáneas no se confirmen las dos.
