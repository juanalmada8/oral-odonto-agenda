# 0006 · Mulish como única tipografía

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

La hoja de estilos declaraba `"Avenir Next"` antes que `"Mulish"`. Avenir Next solo existe en Mac y
iPhone y no se puede distribuir con un sitio web: quien usara Apple veía una tipografía y el resto
de los pacientes (Android, Windows) otra.

## Decisión

**Mulish**, que viaja con el sitio (`app/static/fonts/mulish-variable.woff2`, fuente variable de
peso 200 a 1000), es la primera y principal del conjunto. Lo que sigue en la lista solo cubre el
instante previo a que termine de cargar. El título de la portada usa el peso máximo (1000) con un
espaciado de -0.02em.

## Consecuencias

Todos los dispositivos ven lo mismo. En los emails no se puede garantizar: Gmail y Outlook bloquean
las fuentes web, así que ahí cae a `Helvetica Neue`, `Arial` o la sans-serif del sistema.
