# Recordatorios por WhatsApp (Cloud API de Meta)

El recordatorio sale con dos botones: **Confirmo asistencia** y **Necesito cancelar**. Cancelar pide
una segunda confirmación, así un toque sin querer no libera un turno pago.

## 1. Crear la app en Meta

1. [developers.facebook.com](https://developers.facebook.com/) → **Mis apps** → **Crear app** →
   tipo **Empresa**.
2. Agregá el producto **WhatsApp**. Vas a obtener un número de prueba y un
   **Identificador del número de teléfono** (`WHATSAPP_PHONE_NUMBER_ID`).
3. Para producción, verificá el negocio y registrá el número real de la clínica (no puede ser un
   número que ya use la app de WhatsApp común).
4. **Token permanente:** Configuración del negocio → Usuarios del sistema → crear usuario con rol
   admin → *Generar token* con permisos `whatsapp_business_messaging` y `whatsapp_business_management`.
   Ese es `WHATSAPP_ACCESS_TOKEN` (los tokens temporales vencen en 24 h).
5. `WHATSAPP_APP_SECRET`: Configuración de la app → Básica → *Clave secreta de la app*. Se usa para
   verificar la firma de cada webhook.

## 2. Plantilla del recordatorio

WhatsApp exige una plantilla aprobada para escribirle primero a alguien. Creala en
**WhatsApp Manager → Plantillas de mensajes**:

- **Nombre:** `recordatorio_turno` (o cambiá `WHATSAPP_REMINDER_TEMPLATE`)
- **Categoría:** Utilidad
- **Idioma:** Español (ARG) — `es_AR`
- **Cuerpo:**

  ```
  Hola {{1}}, te recordamos tu turno en ORAL odontología familiar el {{2}} a las {{3}} h con {{4}}. ¿Confirmás tu asistencia?
  ```

- **Botones:** dos de tipo *Respuesta rápida*:
  1. `Confirmo asistencia`
  2. `Necesito cancelar`

Los parámetros que manda la app son, en orden: nombre del paciente, día
("lunes 30 de marzo"), hora ("09:00") y profesional.

## 3. Webhook

En la app de Meta → WhatsApp → Configuración → Webhooks:

- **URL de devolución:** `https://TU-DOMINIO/webhooks/whatsapp`
- **Token de verificación:** el mismo valor que cargues en `WHATSAPP_VERIFY_TOKEN`.
- Suscribite al campo **messages**.

La verificación inicial (GET) la responde la app sola si el token coincide.

## 4. Variables

| Variable | Para qué |
| --- | --- |
| `WHATSAPP_ACCESS_TOKEN` | enviar mensajes |
| `WHATSAPP_PHONE_NUMBER_ID` | número emisor |
| `WHATSAPP_APP_SECRET` | verificar la firma de los webhooks |
| `WHATSAPP_VERIFY_TOKEN` | alta del webhook |
| `WHATSAPP_REMINDER_TEMPLATE` | nombre de la plantilla (`recordatorio_turno`) |
| `WHATSAPP_TEMPLATE_LANGUAGE` | idioma de la plantilla (`es_AR`) |

Sin estas variables el sistema sigue funcionando: los recordatorios salen solo por email.

## 5. Números argentinos

Los celulares se normalizan a formato internacional con el 9 (`+54 9 11 5555-5555`), que es el que
usa WhatsApp. El paciente puede escribir `11 5555-5555`, `011 15 5555-5555` o `+5491155555555`: la
app los interpreta igual, y al responder compara el número ignorando ese 9.

## 6. Costos y límites

- Las conversaciones de *utilidad* iniciadas por la clínica se cobran por conversación (tarifa de
  Argentina, centavos de dólar). Un recordatorio por turno es lo habitual.
- Responder dentro de las 24 h posteriores a un mensaje del paciente es gratis: por eso las
  respuestas del bot (confirmación, cancelación) no generan costo adicional.

## 7. Diagnóstico

| Síntoma | Dónde mirar |
| --- | --- |
| No llega el recordatorio | Panel → Notificaciones: estado y error de cada mensaje |
| "WhatsApp no configurado" | Falta alguna de las variables; el panel muestra el estado |
| Los botones no hacen nada | Webhook mal suscrito o firma inválida (revisá `WHATSAPP_APP_SECRET`) |
| Error 131047 / 131026 | Plantilla no aprobada o número inexistente en WhatsApp |
