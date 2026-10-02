# 0007 · Titularidad: el negocio es del consultorio, el repositorio y la nube los administra quien desarrolla

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

ORAL es un negocio de la titular del consultorio. Quien desarrolla el sistema lo administra además
técnicamente: es dueño del repositorio de GitHub y del proyecto de Google Cloud, bajo sus cuentas
personales.

## Decisión

- El **repositorio** y el **proyecto de Google Cloud** (con su facturación) permanecen en las cuentas
  de quien desarrolla y administra. No se crea una organización de GitHub ni se transfiere el repositorio.
- El **dominio** (`oral.com.ar`) está registrado a nombre del consultorio, no de quien desarrolla.
- El panel tiene **dos administradores** (uno por cada persona), porque no existe recuperación de
  contraseña por email.
- El acceso de GitHub a Google Cloud está atado al nombre del repositorio (`github_repository` en
  Terraform): si el repositorio cambia de cuenta u organización hay que actualizarlo y volver a aplicar
  ([DEPLOYMENT.md](../DEPLOYMENT.md)).

## Consecuencias

El riesgo principal es el de dependencia de una sola persona: **si quien administra no está disponible,
el consultorio no puede desplegar cambios, rotar secretos ni acceder a la nube**. El sistema ya en
producción sigue funcionando solo (la tarea programada y los backups no dependen de nadie), pero no
se puede modificar.

Medidas que reducen ese riesgo y que **siguen pendientes de decidir**:

- Sumar a la titular, o a una persona de confianza, como propietaria del proyecto de Google Cloud y de la
  cuenta de facturación.
- Sumar un segundo administrador al repositorio de GitHub.
- Guardar una copia de `terraform.tfvars` en un gestor de contraseñas compartido
  (no se versiona; ver [DEPLOYMENT.md](../DEPLOYMENT.md)).

Si más adelante se decide cambiar la titularidad, se escribe una decisión nueva que reemplace a esta.
