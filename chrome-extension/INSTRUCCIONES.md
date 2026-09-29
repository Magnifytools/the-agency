# Agency Manager — Extensión de Chrome

## Instalación

1. Abre Chrome y ve a `chrome://extensions`
2. Activa **Modo desarrollador** (esquina superior derecha)
3. Haz clic en **"Cargar descomprimida"**
4. Selecciona la carpeta `chrome-extension` (esta carpeta)
5. La extensión aparece en la barra de herramientas (icono **A** amarillo)

## Uso

1. Haz clic en el icono **A** en la barra de herramientas
2. La primera vez: introduce tu correo y contraseña de The Agency y pulsa **Iniciar sesión**.
3. En **Hacer**, elige **Pedir** para hacer una petición o consulta, **Aclarar** para guardar una nota en el Inbox, o **Tarea directa** para crear una tarea asignada a ti.
4. En **Timer**, inicia o registra tiempo para una tarea. En **Tareas**, consulta tus tareas asignadas, complétalas o inicia el timer.

Las notas sin cliente o proyecto elegido se clasifican automáticamente. Puedes añadirles un enlace relacionado de forma opcional. **Avisos de reuniones** permite activar notificaciones de Chrome y elegir su antelación, siempre que los avisos generales estén activos.

## Listas y asignación

Los selectores cargan todas las páginas de clientes, proyectos y tareas. Si una carga falla, aparece un aviso con opción de reintentar y se conserva la última lista completa y la selección actual. Una captura fallida conserva el texto y la asignación para volver a enviarla. Al elegir un proyecto para una nota, se envían su proyecto y su cliente; al elegir un cliente, se envía ese cliente. Solo las notas sin asignación se clasifican automáticamente.

## Pruebas locales

Desde esta carpeta, con Node.js 24:

```bash
npm ci
npm test
```

Las pruebas ejecutan el HTML y el JavaScript reales del popup en un DOM con Chrome/API simulados. Cubren varias páginas (135 clientes, 128 proyectos y 126 tareas), errores intermedios, reintento, sesión caducada, respuestas posteriores al logout y el cuerpo enviado al Inbox. No llaman a producción. Las dependencias de pruebas no forman parte de la extensión empaquetada.

## Distribución

No hay compilación de JavaScript: Chrome carga los archivos de esta carpeta directamente. `build.sh` copia únicamente manifest, popup, background e iconos a un directorio temporal y firma el CRX con la clave externa existente. No incluir claves en esta carpeta ni generar una identidad nueva para actualizar instalaciones existentes.

Cambiar el código fuente no actualiza automáticamente los archivos CRX o ZIP ya distribuidos. Para una publicación hay que aumentar la versión del manifiesto, regenerar el CRX con la identidad existente y preparar el ZIP desde los mismos archivos fuente; comprobar que ambos contienen esa misma versión y contenido antes de distribuirlos.

### Actualizar una instalación cargada como carpeta descomprimida

El equipo usa **Cargar descomprimida**: publicar `update.xml` y el CRX no actualiza esa instalación. Entrega el ZIP de la versión nueva, descomprímelo y sustituye los archivos dentro de **la misma carpeta** que Chrome ya tiene cargada. Después, en `chrome://extensions`, pulsa **Recargar** en The Agency y comprueba el número de versión. Mantener la ruta de la carpeta evita crear otra instalación y conserva el almacenamiento local de la extensión.
