# Fase 1 · Ficha de cliente en 4 bloques

Plan Agency 2.0, mejora 6 (+ parte de la 7). La ficha no se abrió en 30 días;
su pestaña por defecto ("Ficha") sólo enseñaba contexto y contacto.

## Diseño (el diagrama del plan)

La pestaña por defecto pasa a ser **Vista general**, de arriba abajo:

1. **Estado** (ancho completo): la misma tarjeta que la Cartera.
2. Tres bloques en columnas:
   - **Trabajo**: tareas abiertas (las 5 más urgentes por fecha), las que están
     en revisión, horas del mes. Enlace a Tareas.
   - **Resultados**: tráfico de Google y estado del resumen (mismas celdas que
     la Cartera); enlaces a Resúmenes, a la pestaña SEO y al informe PDF de
     The Engine si el cliente está vinculado.
   - **Relación**: interlocutor principal, extracto del contexto y
     seguimientos con el cliente (tareas en espera, con su fecha). Enlace a
     Contexto y Contactos.

Áreas: **Vista general** (Vista general, Actividad) · **Trabajo** (Tareas,
Proyectos, Tiempo) · **Resultados** (Resúmenes, SEO, Panel y los módulos
ocultos si se reactivan) · **Relación** (Contexto, Contactos). **Ajustes** y
Facturas salen de las áreas a un botón con engranaje en la cabecera.

- La antigua pestaña "Ficha" (contexto editable + interlocutor) pasa a
  `?tab=contexto`. `?tab=ficha` sigue funcionando y abre la Vista general.
- Las tarjetas de KPI (total tareas, tiempo) quedan sólo en Panel.
- Sin endpoints nuevos: estado (`/status`), resumen del cliente (tareas) y
  contactos ya existen.

## Fuera
- Notas del inbox por cliente: el inbox sólo lista notas propias y no filtra
  por cliente; mostrarlas a medias sería engañoso.
- "Cambios en la web" (Vigil): sin integración todavía.
