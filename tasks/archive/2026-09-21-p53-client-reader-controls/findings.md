# Hallazgos P53

- `ClientSettingsTab` permite editar GA4/GSC y muestra Guardar sin consultar `clients.write`; el API exige ese permiso.
- La tarjeta de inteligencia de negocio en `ClientDetailPage` muestra lápiz y guardado sin el mismo guard.
- Las PR 74–76 corrigieron tareas/proyectos, no estas dos superficies de cliente.
- La primera prueba focal detectó una rama ternaria JSX incompleta antes de ejecutar la página; se corrigió y se repite el gate focal.
- El build detectó una coma residual al convertir el árbol de prueba en una función de rerender; se corrigió antes del gate final.
- `npm run lint` sigue rojo por 20 errores preexistentes fuera de P53 (pureza de React, refs y efectos en dashboard, proposals, reports, timer y páginas financieras); los tres archivos modificados no aparecen en la salida.
