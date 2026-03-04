# Auditoría Profunda The-Agency (Pasada 3: código + vivo desktop/móvil)

Fecha: 2026-02-26  
Proyecto: `the-agency`  
Tipo: Auditoría integral (revisión de código + ejecución real UI + revalidación API de seguridad)  
Estado: Finalizado

## 0) Objetivo de esta pasada

Realizar una tercera pasada en profundidad para validar:

1. Estado actual real tras los fixes de la pasada anterior.
2. Cobertura funcional pantalla por pantalla (desktop y móvil), con click sweep controlado.
3. Seguridad y autorizaciones en vivo (JWT, RBAC, integraciones, errores 5xx).
4. Matriz de riesgos actualizada y plan de remediación final.

---

## 1) Resumen ejecutivo

Estado global actual: **Mejorado de forma importante**, pero todavía con **1 riesgo crítico abierto** y **2 riesgos funcionales relevantes**.

### Resultado global de ejecución viva

- Desktop: **24/24 rutas OK**, `87` clicks, `0` fallos de click.
- Móvil: **24/24 rutas OK**, `86` clicks, `0` fallos de click.
- Eventos runtime:
  - Desktop: `2` eventos (1 `api_http_error=403` en export CSV, 1 `console.error` asociado).
  - Móvil: `0` eventos.
- Sin `pageerror` en desktop/móvil en la pasada v8.

### Riesgos abiertos prioritarios

1. **[CRÍTICO] JWT forjable si se mantiene la secret por defecto**.
2. **[ALTO] Export CSV de Facturación falla con 403 en UI (desktop)** por flujo sin auth header.
3. **[MEDIO] `/api/discord/send-daily-summary` devuelve 500** ante webhook inválido/no entregable.
4. **[MEDIO] `GET /api/users` accesible para member** (sanitizado, pero sigue exponiendo listado de staff).

### Cambios positivos confirmados respecto pasada 2

- Corregido crash de dashboard (`InsightCard`/`quality`).
- Corregido 500 de Holded (`dashboard`, `invoices`, `expenses`).
- Corregido 500 de Timesheet por naive/aware.
- Corregido 500 de `/api/digests/generate`.
- Corregido acceso member a `GET /api/users/{id}` de terceros.
- JWT sin `exp` ya no se acepta.

---

## 2) Alcance y metodología

## 2.1 Revisión de código (backend + frontend)

Foco en:

- Auth/JWT y dependencias de seguridad.
- RBAC/permissions en módulos sensibles.
- Endpoints de integración (Discord/Holded/Digests).
- Flujos UI de exportaciones y navegación crítica.

## 2.2 Ejecución viva UI (desktop + móvil)

Pasada válida final: **`deep-pass-2026-02-26-v8`**.

Detalles:

- Login real vía UI.
- Navegación explícita por 24 rutas.
- Click sweep controlado en contenido de pantalla (sin sesgo de sidebar/nav global).
- Captura por ruta de:
  - `expected_ok` por token esperado.
  - `clicked_count` y `click_failures`.
  - screenshots desktop/móvil.
  - eventos de consola/network.

Nota técnica de control: una corrida previa (`v7`) quedó descartada para criterio final por deriva de navegación en mobile; `v8` corrige ese sesgo y es la base del informe.

## 2.3 Revalidación API de seguridad en vivo

Batería en backend local de `the-agency` (`127.0.0.1:8004`) sobre:

- JWT forjado (con y sin `exp`).
- RBAC member/admin en usuarios/finanzas/holded.
- Integraciones Discord/Holded/Digests.
- Timesheet con fechas `Z` y sin `Z`.

---

## 3) Evidencia usada (artefactos)

- Overview corrida v8:  
  `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-26-v8/run-overview.json`
- Summary desktop v8:  
  `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-26-v8/desktop-summary.json`
- Summary móvil v8:  
  `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-26-v8/mobile-summary.json`
- Recheck API seguridad (pasada 3):  
  `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-26.txt`
- Log backend recheck API:  
  `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-26-backend.log`

Screenshots por ruta (desktop/móvil):

- Carpeta: `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-26-v8/`
- Archivos: `desktop-01..24-*.png`, `mobile-01..24-*.png`

---

## 4) Cobertura funcional completa (pantalla por pantalla)

| Ruta | Desktop ok | D clicks | D fail | Mobile ok | M clicks | M fail |
|---|---:|---:|---:|---:|---:|---:|
| `/dashboard` | true | 8 | 0 | true | 8 | 0 |
| `/clients` | true | 5 | 0 | true | 8 | 0 |
| `/leads` | true | 4 | 0 | true | 4 | 0 |
| `/projects` | true | 4 | 0 | true | 4 | 0 |
| `/tasks` | true | 8 | 0 | true | 8 | 0 |
| `/growth` | true | 2 | 0 | true | 2 | 0 |
| `/timesheet` | true | 0 | 0 | true | 0 | 0 |
| `/digests` | true | 6 | 0 | true | 6 | 0 |
| `/reports` | true | 2 | 0 | true | 2 | 0 |
| `/proposals` | true | 6 | 0 | true | 8 | 0 |
| `/billing` | true | 1 | 0 | true | 1 | 0 |
| `/finance` | true | 0 | 0 | true | 0 | 0 |
| `/finance/income` | true | 2 | 0 | true | 2 | 0 |
| `/finance/expenses` | true | 2 | 0 | true | 2 | 0 |
| `/finance/taxes` | true | 3 | 0 | true | 3 | 0 |
| `/finance/forecasts` | true | 3 | 0 | true | 3 | 0 |
| `/finance/advisor` | true | 2 | 0 | true | 2 | 0 |
| `/finance/import` | true | 0 | 0 | true | 0 | 0 |
| `/users` | true | 2 | 0 | true | 2 | 0 |
| `/discord` | true | 3 | 0 | true | 3 | 0 |
| `/finance-holded` | true | 7 | 0 | true | 5 | 0 |
| `/clients/2` | true | 6 | 0 | true | 1 | 0 |
| `/leads/2` | true | 7 | 0 | true | 8 | 0 |
| `/projects/2` | true | 4 | 0 | true | 4 | 0 |

### Métricas agregadas

- Desktop:
  - rutas: `24`
  - expected ok: `24`
  - clicks: `87`
  - click failures: `0`
  - tiempo agregado de rutas: `82,352 ms` (~82.4 s)
- Móvil:
  - rutas: `24`
  - expected ok: `24`
  - clicks: `86`
  - click failures: `0`
  - tiempo agregado de rutas: `83,732 ms` (~83.7 s)

### Eventos runtime de la corrida válida

- Desktop:
  - `GET /api/billing/export?...` -> `403` en ruta `/billing`.
  - `console.error`: recurso bloqueado por 403 (mismo evento).
- Móvil: sin eventos.

---

## 5) Hallazgos abiertos (priorizados)

## 5.1 [CRÍTICO] C-01: JWT forjable si se usa la `SECRET_KEY` por defecto

### Evidencia viva

Archivo: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-26.txt`

- Token forjado con secret default **y con `exp`** -> `GET /api/auth/me` responde `200`.
- Token forjado sin `exp` -> `401` (esta parte sí está corregida).

### Evidencia en código

- `backend/config.py:8` define `DEFAULT_SECRET_KEY = "dev-secret-change-in-production"`.
- `backend/config.py:13` usa esa clave como default real de `SECRET_KEY`.
- `backend/core/security.py:29-34` ya exige `require_exp=True` (mejora), pero no evita el riesgo de secreto débil/conocido.

### Impacto

- Suplantación de identidad (incluido admin) si despliegas con secret por defecto.
- Compromiso de autenticación/autorización.

### Recomendación

1. Bloquear arranque en `production` si `SECRET_KEY` es default o no cumple entropía mínima.
2. Rotar clave en producción y revocar tokens/sesiones.
3. Añadir validaciones de claims (`exp` ya está, añadir `iat` y opcionalmente `iss`/`aud` según arquitectura).

---

## 5.2 [ALTO] H-01: Export CSV de Facturación falla con 403 en UI (desktop)

### Evidencia viva

Archivo: `desktop-summary.json` (pasada v8)

- Evento: `api_http_error` 403
- URL: `/api/billing/export?format=csv&year=2026&month=2`
- Ruta: `/billing`

### Evidencia en código

- Frontend export:
  - `frontend/src/pages/billing-page.tsx:29-32`
  - Usa `window.location.href = /api/billing/export...`.
- Backend endpoint protegido:
  - `backend/api/routes/billing.py:34`
  - Requiere `Depends(require_module("billing"))`.

### Causa raíz

El flujo de descarga CSV no usa el cliente API con interceptor de auth (Bearer). Al navegar con `window.location.href`, la petición llega sin cabecera `Authorization` y el backend responde `403`.

### Impacto

- Botón principal de exportación no funcional para sesiones SPA típicas.
- UX de error y ruido de consola.

### Recomendación

1. Descargar CSV con `axios` autenticado (`responseType: "blob"`) y forzar descarga desde blob URL.
2. Alternativa: endpoint de descarga con token temporal firmado de un solo uso.

---

## 5.3 [MEDIO] M-01: `/api/discord/send-daily-summary` responde 500 cuando falla entrega

### Evidencia viva

Archivo: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-26.txt`

- `POST /api/discord/test-webhook` -> `200` con `success:false` (controlado).
- `POST /api/discord/send-daily-summary` -> `500` con `{"detail":"Error al enviar a Discord"}`.

### Evidencia en código

- `backend/api/routes/discord.py:189-201`
- Si `success` es false, el endpoint eleva `HTTPException(500)`.

### Impacto

- Semántica inconsistente con `test-webhook`.
- Errores 500 por problema externo de integración (no necesariamente fallo interno del servidor).

### Recomendación

1. Homogeneizar contrato de integración externa:
   - `200` con `success:false` para fallo de entrega controlado, o
   - `502/503` si se considera upstream dependency failure.
2. Incluir `reason_code` (`invalid_webhook`, `timeout`, `network_error`).

---

## 5.4 [MEDIO] M-02: `GET /api/users` sigue accesible para member (listado organizacional)

### Evidencia viva

Archivo: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-26.txt`

- Member: `GET /api/users?page_size=999` -> `200`.
- El `hourly_rate` llega saneado a `null` (mejora implementada).

### Evidencia en código

- `backend/api/routes/users.py:16-41`
- La ruta permite acceso a autenticados; para no-admin aplica sanitización parcial, pero no restringe listado.

### Impacto

- Exposición de nombres/emails/roles del equipo a cualquier member autenticado.
- Riesgo de privacidad interna dependiendo de política de la agencia.

### Recomendación

1. Definir política explícita:
   - opción A: listado completo solo admin;
   - opción B: listado reducido para asignaciones (id + nombre).
2. Si se mantiene visible, eliminar email para members o limitar por tenant/team scope.

---

## 6) Hallazgos cerrados (confirmados en pasada 3)

| ID previa | Estado pasada 2 | Estado pasada 3 | Evidencia |
|---|---|---|---|
| Dashboard crash `InsightCard` (`quality`) | Abierto | **Cerrado** | `run-overview v8`: `pageerror=0` desktop y móvil |
| Holded 500 (`dashboard/invoices/expenses`) | Abierto | **Cerrado** | Recheck API: todos `200` |
| Timesheet 500 naive/aware | Abierto | **Cerrado** | Recheck API: `time-entries` con/sin `Z` y `weekly` en `200` |
| `POST /api/digests/generate` 500 | Abierto | **Cerrado** | Recheck API: `200` |
| Member `GET /api/users/{id}` tercero | Abierto | **Cerrado** | Recheck API: `403` |
| JWT sin `exp` aceptado | Abierto | **Cerrado** | Recheck API: token sin exp -> `401` |

---

## 7) Segunda pasada de seguridad (matriz actualizada)

| Control | Prueba | Resultado | Estado |
|---|---|---|---|
| JWT forged con secret default + `exp` | `GET /api/auth/me` | `200` | **FAIL (Crítico)** |
| JWT forged sin `exp` | `GET /api/auth/me` | `401` | PASS |
| Member ve listado usuarios | `GET /api/users?page_size=999` | `200` | FAIL (política) |
| Member ve perfil tercero | `GET /api/users/1` | `403` | PASS |
| Member cambia permisos | `PUT /api/users/1/permissions` | `403` | PASS |
| Member accede finanzas ingresos | `GET /api/finance/income` | `403` | PASS |
| Member accede holded config | `GET /api/holded/config` | `403` | PASS |
| Timesheet con `Z` | `GET /api/time-entries?...Z` | `200` | PASS |
| Weekly timesheet | `GET /api/time-entries/weekly` | `200` | PASS |
| Holded dashboard | `GET /api/holded/dashboard` | `200` | PASS |
| Holded invoices/expenses | `GET /api/holded/invoices|expenses` | `200` | PASS |
| Discord test webhook | `POST /api/discord/test-webhook` | `200 success:false` | PASS (controlado) |
| Discord send daily | `POST /api/discord/send-daily-summary` | `500` | FAIL (contrato) |
| Digests generate | `POST /api/digests/generate` | `200` | PASS |

### Matriz de riesgo (probabilidad x impacto)

| ID | Riesgo | Probabilidad | Impacto | Nivel | Estado |
|---|---|---|---|---|---|
| SEC-01 | Secret JWT por defecto utilizable | Alta | Crítico | **Crítico** | Abierto |
| APP-01 | Export CSV billing roto por flujo no autenticado | Alta | Alto | **Alto** | Abierto |
| INT-01 | Discord send-daily-summary usa 500 para fallo de entrega | Media | Medio-Alto | **Medio-Alto** | Abierto |
| PRIV-01 | Listado de usuarios visible para members | Media | Medio | **Medio** | Abierto |

---

## 8) Diagnóstico técnico adicional (arquitectura y calidad)

## 8.1 Seguridad y plataforma

1. Añadir guard de arranque en backend para secretos inseguros.
2. Definir políticas de claims JWT y expiración de refresh/access.
3. Añadir rate limiting en `/api/auth/login` (si no está en gateway).
4. Auditoría de permisos por módulo con tests automáticos de matriz rol x endpoint.

## 8.2 Robustez de integraciones

1. Estandarizar errores de proveedores (`discord`, `holded`, LLM):
   - nunca `500` genérico por fallo esperable de red/credenciales.
2. Incorporar `retry + timeout + reason_code`.
3. Telemetría por integración (latencia, ratio éxito, últimos fallos, correlación con UI).

## 8.3 Frontend y UX operacional

1. Reemplazar export por flujo autenticado blob en Facturación.
2. Para pantallas con acciones sensibles, exponer estado de operación y error con detalle útil.
3. Mantener smoke móvil/desktop por ruta crítica en CI (mínimo navegación + token esperado + no pageerror).

---

## 9) Ideas y mejoras de producto (accionables)

1. **Centro de Salud del Workspace**
   - Estado por módulo (CRM, PM, Finanzas, Integraciones) con score diario.
2. **Modo Degradado Inteligente**
   - Si falla proveedor externo, mostrar último dato válido con sello temporal.
3. **Control de Exposición de Personas**
   - Política configurable por rol sobre visibilidad de emails/perfiles.
4. **Export Hub**
   - Todas las exportaciones con cola/estado/histórico y archivos listos para descarga.
5. **Auditoría continua de permisos**
   - job semanal que verifica endpoints sensibles con usuario member simulado.

---

## 10) Plan de remediación (priorizado)

## Fase 0 (0-48h)

1. **Bloqueo de secret insegura** (`SEC-01`).
2. **Fix export CSV autenticado** en Facturación (`APP-01`).
3. **Normalizar contrato `send-daily-summary`** (`INT-01`).

Criterios de salida:

- Token forged con secret default ya no funciona en entorno de despliegue real.
- Click en `Descargar CSV` devuelve archivo correcto y sin 403.
- `send-daily-summary` deja de emitir 500 por fallo controlado de webhook.

## Fase 1 (3-7 días)

1. Definir política final de visibilidad de `GET /api/users` y aplicar (`PRIV-01`).
2. Añadir tests automáticos de regresión para los 4 hallazgos abiertos.
3. Añadir métricas de errores por endpoint e integración.

## Fase 2 (1-2 semanas)

1. Hardening de auth (claims adicionales, expiraciones y revocación).
2. Test suite de seguridad RBAC por rol/módulo.
3. Consolidación de manejo de errores externos con `reason_code` estándar.

---

## 11) Checklist de cierre de esta auditoría

- Revisión de código backend/frontend: Sí.
- Full pass vivo desktop 24/24: Sí.
- Full pass vivo móvil 24/24: Sí.
- Click sweep por pantalla: Sí.
- Revalidación API seguridad: Sí.
- Matriz de seguridad y riesgo actualizada: Sí.
- Estado de hallazgos abiertos vs cerrados: Sí.
- Plan priorizado de remediación: Sí.

---

## 12) Conclusión final

La tercera pasada confirma una mejora fuerte en estabilidad y cobertura funcional real (desktop+móvil), con varios problemas críticos/altos de la pasada anterior ya cerrados. El principal bloqueo para un nivel de seguridad de producción sigue siendo la dependencia de una `SECRET_KEY` por defecto explotable en escenarios mal configurados.

Si se ejecuta Fase 0 inmediatamente, el sistema quedaría en una posición sólida para una nueva ronda de certificación final (smoke + seguridad) con riesgo significativamente menor.
