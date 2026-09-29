# Hallazgos

- Los selectores de estado son `select` nativos. Heredan `text-foreground` blanco de la app oscura, pero el menú de opciones del navegador conserva un fondo claro en algunos entornos. El resultado es texto blanco sobre blanco, como en la captura.
- El mismo selector se reutiliza en la tabla de tareas, «Mi día» y el panel de tarea mediante `taskStatusSelectClass`, por lo que una clase común permite corregir los tres flujos sin afectar el resto de selects.
- La clase común usa `color-scheme: dark` para que el navegador elija el menú nativo oscuro y declara además colores explícitos en `option`. Chromium confirmó mediante estilos calculados `rgb(28, 28, 28)` de fondo y `rgb(255, 255, 255)` de texto.
