# 0005 · La URL de los estáticos lleva el hash de su contenido

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

En producción `asset_url` agregaba `?v=<versión de la app>`, que solo cambia al publicar un release.
Los arreglos de CSS desplegados entre dos releases conservaban la misma URL y los navegadores
seguían sirviendo la copia vieja de su caché: cambios en producción que nadie veía. En desarrollo
no se notaba porque ahí la huella era la fecha del archivo.

## Decisión

`asset_url` usa un **hash SHA-256 del contenido** del archivo, calculado una vez y guardado en
memoria (la imagen de producción es inmutable). La URL cambia exactamente cuando cambia el archivo.

Las fuentes `.woff2` y `.woff` se registran con su tipo MIME real: la imagen Docker `slim` no trae
`/etc/mime.types` y se servían como `application/octet-stream`.

## Consecuencias

Cada despliegue con un estático modificado invalida solo ese estático. No hace falta forzar la
recarga ni versionar a mano. Tests: `test_the_static_url_changes_when_the_file_changes`,
`test_web_fonts_are_served_with_their_real_media_type`.
