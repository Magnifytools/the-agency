# Progreso — reducción de módulos

Estado: **hecho y verificado en local. Sin desplegar.**

## Resultado

| | Antes | Después |
|---|---|---|
| Rutas `/api` registradas | 264 | **135** (−49 %) |
| Entradas en la barra lateral | 17 | **10** |
| Pestañas en el detalle de cliente | 10 grupos | **8** |

Barra lateral final: Dashboard · Clientes · Proyectos · Tareas · Inbox ·
Timesheet · Dailys · Digests · Equipo · Ajustes.

## Cómo funciona

Un interruptor por módulo, en dos ficheros que un test mantiene sincronizados:

- `backend/core/modules.py` — `HIDDEN_MODULES`, sobreescribible con la variable
  de entorno `AGENCY_HIDDEN_MODULES` (reactivar en Railway **sin desplegar**).
- `frontend/src/lib/hidden-modules.ts` — la misma lista + el mapa de rutas.
- `backend/tests/test_hidden_modules.py` — 44 tests: compara ambas listas, y
  levanta la app **en un subproceso limpio** con la configuración de producción
  para comprobar qué routers quedan registrados de verdad.

`frontend/src/components/layout/hidden-module-gate.tsx` redirige al dashboard
cualquier ruta oculta. Es UN guardián, no un envoltorio por ruta, para que no
pueda desincronizarse.

## Tres cosas que cambiaron sobre el plan, al verificar

**1. `discord` y `my_week`: pantalla oculta, API viva.**
El plan decía apagar sus routers. Al navegar la app apareció que:
- el dashboard lee `/api/discord/settings` para ofrecer «Enviar a Discord» en el
  Resumen Diario — y ese envío sí se usa (43 veces en 77 días);
- Ajustes gestiona los festivos de empresa en `/api/my-week/holidays`.

Apagarlos habría roto un trozo de dos pantallas conservadas. Sus routers están
en `_CORE_ROUTERS` con el motivo escrito al lado. **Ocultar una pantalla y apagar
una API son decisiones distintas**; aquí solo queríamos la primera.

**2. La suite corre con TODO activado.**
Al ocultar los routers, 123 tests pasaron a fallar: eran los de los módulos
ocultos. En vez de mantener una lista de *skips* que se pudriría, `conftest.py`
fija `AGENCY_HIDDEN_MODULES=""`, así el código oculto **sigue probado** para
cuando se reactive. La configuración real se verifica aparte, en subproceso.

**3. Bug encontrado de paso (arreglado): faltaban dos columnas del cronómetro.**
`time_entries.paused_at` y `.accumulated_seconds` están en el modelo pero **no**
en el DDL de arranque, y `create_all` no añade columnas a tablas existentes.
Cualquier base anterior a la función de pausa devuelve **500 en
`GET /api/timer/active`** — el endpoint más consultado y el núcleo del producto.
Producción funciona porque se añadieron a mano, como pasó con el enum
`vattreatment`. Un entorno nuevo o una restauración de backup se quedaba sin
cronómetro. Añadidas al DDL.

## Verificación

- Backend **471 tests** en verde (incluida integración con Postgres real).
- `npx tsc --noEmit` limpio, `npm run test` 45 en verde, `npm run build` OK.
- App levantada en local y **navegada de verdad**: dashboard, clientes, detalle
  de cliente, proyectos, tareas, timesheet, dailys, digests, ajustes.
  **Todas las peticiones 200. Ni un 404 ni un 500.**
- Rutas ocultas (`/reports`, `/leads/42`) redirigen al dashboard.
- `?tab=comunicaciones` en un cliente cae a Ficha en vez de renderizar la
  pestaña oculta.

## Pendiente

- ~~**Desplegar.**~~ Hecho. Verificado el 19 ago 2026 contra
  `agency.magnifytools.com`: `/api/leads`, `/api/growth/ideas` y `/api/reports`
  devuelven 404 y `/api/tasks` responde 401. Está en producción.
- **Ocultar no ahorraba arranque** (encontrado el 19 ago 2026, PR #7):
  `main.py` importa todos los routers y luego decide cuáles registra, así que
  `core_updates` seguía arrastrando sklearn + numpy en cada boot — 244 → 146 MB
  de RSS y 1,19 s. Arreglado con import perezoso. Merece la pena revisar si
  algún otro módulo oculto pesa al arrancar.
- Decidir, dentro de unas semanas, qué se borra de verdad. La lista de
  candidatos es `HIDDEN_MODULES`.
- Si algún día se borra `my_week`, sacar antes los festivos a otro router.
- Quedan registradas 3 rutas de facturación dentro de `projects.py`
  (`billing-summary`, `invoice-tasks`, `mark-billed`) porque viven en un fichero
  que se conserva. Sin UI que las llame.
- `sklearn` + `numpy` siguen en `requirements.txt` aunque `core_updates` esté
  oculto: quitarlos son ~100 MB menos de imagen, pero eso ya es borrar, no ocultar.
