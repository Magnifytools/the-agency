# Hallazgos

- La accion `Estructurar con IA` se renderiza solo cuando existe `base`; un cierre nuevo con notas o fuentes seleccionadas muestra unicamente `Guardar borrador`.
- Cuando hay una base pero el usuario cambia texto o fuentes, el boton de IA queda deshabilitado y una nota separada exige guardar primero. El recorrido obliga a descubrir dos acciones secuenciales.
- La API ya separa correctamente persistencia y estructuracion: `POST/PUT /dailys` guarda el borrador y `POST /dailys/{id}/reparse` procesa exactamente su revision.
- La solucion limpia es componer ambas operaciones en la accion explicita de IA: persistir la version si hace falta y, con el ID/revision devuelto, pedir la estructura. No interviene ninguna ruta de envio.
- La suite focal no pudo arrancar inicialmente porque el worktree nuevo aun no tenia dependencias (`vitest: command not found`); se instalaran con el lockfile antes de la validacion.
- La regresion previa al cambio fallo exactamente porque el CTA no existia. Despues del cambio, el flujo crea el borrador con texto y claves de fuentes, llama a `reparse` con el ID/revision confirmados y no invoca ninguna ruta de envio.
- La suite completa en paralelo no fue una senal valida en esta maquina: acumulo timeouts en decenas de archivos no relacionados, incluidos tres casos del propio daily que pasan aislados. Las suites focal y adyacente pasan por separado.
- El build conserva un aviso CSS preexistente sobre el orden de un `@import` de Google Fonts; no afecta a esta ruta ni impide compilar.
