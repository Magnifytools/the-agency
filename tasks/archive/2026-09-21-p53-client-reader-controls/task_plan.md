# P53 — controles de cliente para lectores

## Objetivo

Evitar que un miembro con `clients.read` y sin `clients.write` vea controles que guardan datos en la ficha activa de cliente. Mantener las lecturas y descargas; reservar la inteligencia generada para administradores.

## Pasos

1. Establecer el baseline de las pruebas frontend afectadas.
2. Hacer que Ficha, Contactos, Actividad, Panel y Ajustes consulten el permiso actual y no disparen mutaciones sin él.
3. Añadir regresiones de lector, escritor y administrador para las superficies afectadas.
4. Ejecutar pruebas focales, lint y build.
