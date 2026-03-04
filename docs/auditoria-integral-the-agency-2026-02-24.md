# Auditoría Integral de Plataforma - The Agency

Fecha: 24 de febrero de 2026
Tipo de revisión: Estática de código + validación técnica (sin cambios en código)
Alcance: Backend FastAPI, Frontend React/Vite, configuración e infraestructura local del repositorio

---

## 1) Resumen ejecutivo

Estado general: la aplicación tiene una base funcional sólida, pero presenta brechas críticas de seguridad y autorización que deben corregirse antes de escalar a producción multiusuario.

Riesgo global actual: **ALTO**

Principales conclusiones:
- Se detectó una vulnerabilidad crítica de **path traversal** en el fallback de archivos estáticos.
- El modelo de permisos existe, pero la aplicación de autorización está incompleta e inconsistente en backend.
- Hay varios casos de acceso horizontal (IDOR/BOLA) sobre recursos sensibles.
- Existen problemas funcionales que rompen flujos concretos (PM insights, inbox, navegación de tareas).
- Hay deuda técnica relevante en frontend (lint roto y bundle principal sobredimensionado).

Conteo de hallazgos por severidad:
- Crítico (P0): 4
- Alto (P1): 7
- Medio (P2): 7
- Bajo (P3): 2

---

## 2) Alcance y metodología

### 2.1 Componentes revisados
- Backend: `backend/main.py`, `backend/config.py`, `backend/api/routes/*`, `backend/services/*`, `backend/db/models.py`, `backend/db/seed.py`, migraciones, schemas y dependencias.
- Frontend: `frontend/src/lib/*`, `frontend/src/context/*`, `frontend/src/components/*`, `frontend/src/pages/*`, enrutado y navegación.
- Infra: `Dockerfile`, `docker-compose.yml`, `.env.example`.

### 2.2 Validaciones ejecutadas
- `frontend`: `npm run lint`.
- `frontend`: `npm run build`.
- `backend`: compilación sintáctica con `compileall` usando `PYTHONPYCACHEPREFIX=/tmp/pycache`.

### 2.3 Resultado de validaciones
- `npm run lint`: falla con **19 errores**.
- `npm run build`: OK, warning de chunk grande (`dist/assets/index-*.js` ≈ 978.75 kB minificado).
- `compileall`: OK en backend (sin errores de sintaxis).

---

## 3) Hallazgos detallados

## F-01 [P0 Crítico] Path traversal en fallback SPA
- Tipo: Vulnerabilidad
- OWASP API: API8 Security Misconfiguration
- Evidencia:
  - `backend/main.py:76`
  - `backend/main.py:78`
  - `backend/main.py:80`
- Descripción: el fallback `/{full_path:path}` construye `file_path = _frontend_dist / full_path` y sirve el archivo si existe. No hay normalización ni validación de que el path resuelto permanezca dentro de `frontend/dist`.
- Impacto: lectura arbitraria de archivos del servidor (código fuente, configuración, potenciales secretos en archivos legibles).
- Prueba técnica local (resolución de ruta): `frontend/dist/../../backend/main.py` existe y resuelve fuera de `dist`.
- Recomendación:
  - Resolver ruta con `.resolve()`.
  - Verificar prefijo estricto contra `_frontend_dist.resolve()`.
  - Si sale de raíz, responder 404.
  - Añadir test de regresión para `../` y variantes URL encoded.
- Esfuerzo estimado: S (2-4h)

## F-02 [P0 Crítico] Bypass de autorización por módulo en múltiples rutas
- Tipo: Vulnerabilidad
- OWASP API: API5 Broken Function Level Authorization
- Evidencia (rutas sin `require_module`, solo `get_current_user`):
  - `backend/api/routes/proposals.py:37`
  - `backend/api/routes/growth.py:21`
  - `backend/api/routes/reports.py:58`
  - `backend/api/routes/billing.py:33`
  - `backend/api/routes/time_entries.py:69`
  - `backend/api/routes/task_categories.py:16`
- Evidencia frontend (solo ocultación visual):
  - `frontend/src/components/layout/app-layout.tsx:24`
  - `frontend/src/components/layout/protected-route.tsx:5`
- Descripción: el frontend esconde navegación por permiso, pero el backend permite acceso por URL/API a varios módulos con solo estar autenticado.
- Impacto: usuarios con permisos limitados pueden invocar endpoints de módulos no autorizados.
- Recomendación:
  - Aplicar `require_module` a todas las rutas funcionales.
  - Definir mapeo único `ruta -> módulo` y cubrirlo con tests automáticos.
- Esfuerzo estimado: M (1-2 días)

## F-03 [P0 Crítico] `can_write` no se aplica en backend
- Tipo: Vulnerabilidad
- OWASP API: API3 Broken Object Property Level Authorization / API5
- Evidencia:
  - `backend/api/deps.py:45`
  - `backend/api/deps.py:47`
- Descripción: `require_module` valida solo `can_read`; no diferencia lectura de escritura. Endpoints de creación/edición/borrado aceptan usuarios con permiso de lectura.
- Impacto: escalada horizontal de privilegios dentro del módulo.
- Recomendación:
  - Implementar `require_module(module: str, write: bool = False)`.
  - En POST/PUT/PATCH/DELETE exigir `can_write`.
  - Crear pruebas de autorización negativas para cada módulo.
- Esfuerzo estimado: M (1-2 días)

## F-04 [P0 Crítico] PM insights globales entre usuarios
- Tipo: Vulnerabilidad + defecto de diseño multiusuario
- OWASP API: API1 Broken Object Level Authorization
- Evidencia:
  - Borrado global de insights activos: `backend/api/routes/pm.py:82`, `backend/api/routes/pm.py:84`
  - Listado sin filtro por usuario: `backend/api/routes/pm.py:52`
  - Modificación por ID sin ownership: `backend/api/routes/pm.py:103`, `backend/api/routes/pm.py:125`
  - Modelo con `user_id`: `backend/db/models.py:353`
- Descripción: las operaciones de PM no están aisladas por usuario.
- Impacto: un usuario puede borrar o modificar insights de otros.
- Recomendación:
  - Filtrar por `PMInsight.user_id == current_user.id` (excepto admin con vista global explícita).
  - Al generar, borrar solo insights del usuario actual.
- Esfuerzo estimado: M (1 día)

## F-05 [P1 Alto] IDOR en time entries (lectura/edición/borrado)
- Tipo: Vulnerabilidad
- OWASP API: API1 Broken Object Level Authorization
- Evidencia:
  - `backend/api/routes/time_entries.py:65`
  - `backend/api/routes/time_entries.py:75`
  - `backend/api/routes/time_entries.py:144`
  - `backend/api/routes/time_entries.py:161`
- Descripción: se permite filtrar por `user_id` arbitrario y editar/borrar por `entry_id` sin validación de propietario.
- Impacto: exposición y manipulación de tiempos de terceros.
- Recomendación:
  - Restringir a `current_user.id` para miembros.
  - Permitir alcance global solo a admin/perfil explícito.
- Esfuerzo estimado: M (1 día)

## F-06 [P1 Alto] IDOR en comunicaciones
- Tipo: Vulnerabilidad
- OWASP API: API1 Broken Object Level Authorization
- Evidencia:
  - `backend/api/routes/communications.py:89`
  - `backend/api/routes/communications.py:103`
  - `backend/api/routes/communications.py:129`
- Descripción: operaciones por `comm_id` sin comprobar si el usuario tiene derecho sobre ese recurso/cliente.
- Impacto: lectura/modificación/borrado de comunicaciones ajenas.
- Recomendación:
  - Introducir ownership o política por cliente/proyecto.
  - Verificar autorización por recurso en GET/PUT/DELETE.
- Esfuerzo estimado: M (1 día)

## F-07 [P1 Alto] Reportes accesibles globalmente
- Tipo: Vulnerabilidad
- OWASP API: API1 + API5
- Evidencia:
  - `backend/api/routes/reports.py:61`
  - `backend/api/routes/reports.py:77`
  - `backend/api/routes/reports.py:95`
  - `backend/db/models.py:485`
- Descripción: list/get/delete de reportes sin filtrar por `user_id` y sin control por módulo.
- Impacto: fuga de datos y borrado no autorizado.
- Recomendación:
  - Añadir `require_module("reports")`.
  - Filtrar por `GeneratedReport.user_id` para miembros.
- Esfuerzo estimado: S-M (4-8h)

## F-08 [P1 Alto] Gestión de secretos y credenciales por defecto insegura
- Tipo: Vulnerabilidad
- OWASP API: API8 Security Misconfiguration
- Evidencia:
  - `backend/config.py:8`, `backend/config.py:13`
  - `backend/main.py:24` (solo warning)
  - `backend/db/seed.py:18`, `backend/db/seed.py:25`
  - `docker-compose.yml:5`, `docker-compose.yml:6`
- Descripción: claves y credenciales débiles por defecto.
- Impacto: acceso no autorizado o firma de tokens si se despliega sin hardening.
- Recomendación:
  - Fallar arranque en producción si `SECRET_KEY` es default.
  - Eliminar passwords débiles del seed o forzar override por entorno.
  - Usar secretos rotables en entorno y vault.
- Esfuerzo estimado: S (4-6h)

## F-09 [P1 Alto] `ai_api_key` almacenada en texto plano
- Tipo: Vulnerabilidad
- OWASP API: API3/API8
- Evidencia:
  - `backend/db/models.py:447`
  - `backend/api/routes/dashboard.py:449`
  - `backend/api/routes/dashboard.py:451`
- Descripción: la API key se persiste sin cifrado.
- Impacto: exposición de credenciales en DB/backups/logs.
- Recomendación:
  - Cifrado en reposo a nivel aplicación (KMS/Vault envelope encryption).
  - Evitar devolver o loguear secreto en responses.
- Esfuerzo estimado: M (1-2 días)

## F-10 [P1 Alto] Bug en PM insights por enum inválido (`TaskStatus.todo`)
- Tipo: Bug funcional
- Evidencia:
  - `backend/services/insights.py:216`
  - `backend/services/insights.py:224`
  - `backend/services/insights.py:232`
  - Enum válido: `backend/db/models.py:48-51`
- Descripción: se usa estado no definido en enum.
- Impacto: fallo de ejecución en generación de insights QA.
- Recomendación:
  - Sustituir por `TaskStatus.pending`/lógica real de “tarea activa”.
  - Añadir tests unitarios sobre generación de insights.
- Esfuerzo estimado: S (1-2h)

## F-11 [P1 Alto] Inbox rápido roto por contrato frontend/backend inconsistente
- Tipo: Bug funcional
- Evidencia:
  - Frontend crea tarea sin `client_id` y con `is_inbox`: `frontend/src/components/dashboard/inbox-widget.tsx:23`
  - Backend exige `client_id`: `backend/schemas/task.py:16`
  - Modelo sí tiene `is_inbox`: `backend/db/models.py:283`
- Descripción: el flujo de captura rápida no respeta el esquema backend.
- Impacto: errores 422 o fallos silenciosos en captura.
- Recomendación:
  - Definir contrato real de inbox (endpoint dedicado o `client_id` opcional para inbox).
  - Tipar correctamente en frontend y eliminar `as any`.
- Esfuerzo estimado: M (4-8h)

## F-12 [P2 Medio] Errores de navegación/estilos en detalle de proyecto
- Tipo: Bug UI/UX
- Evidencia:
  - `frontend/src/pages/project-detail-page.tsx:364`
  - `frontend/src/pages/project-detail-page.tsx:373`
  - `frontend/src/pages/project-detail-page.tsx:381`
- Descripción: clases Tailwind rotas por espacios y `Link` inválido (`/ tasks ? id = ...`).
- Impacto: estilos no aplican y navegación rota.
- Recomendación: corregir strings y cubrir con test de smoke E2E.
- Esfuerzo estimado: S (1-2h)

## F-13 [P2 Medio] Riesgo de CSV formula injection
- Tipo: Vulnerabilidad
- OWASP API: API3 / Data handling
- Evidencia:
  - `backend/api/routes/export.py:40`
  - `backend/api/routes/export.py:72`
  - `backend/api/routes/export.py:101`
- Descripción: exporta texto sin neutralizar prefijos de fórmula (`=`, `+`, `-`, `@`).
- Impacto: ejecución de fórmulas al abrir en Excel/Sheets.
- Recomendación: sanitizar celdas prefixando `'` cuando aplique.
- Esfuerzo estimado: S (2-4h)

## F-14 [P2 Medio] Plantilla PDF sin endurecimiento (autoescape/recursos remotos)
- Tipo: Vulnerabilidad
- OWASP API: API7 SSRF (riesgo contextual)
- Evidencia:
  - `backend/api/routes/proposals.py:211`
  - `backend/api/routes/proposals.py:176`
  - `backend/api/routes/proposals.py:225`
- Descripción: render de HTML a PDF con contenido editable y sin política explícita de recursos externos.
- Impacto: posible abuso de render y carga de recursos no deseados.
- Recomendación:
  - Habilitar autoescape en plantilla.
  - Restringir fetch de recursos en renderer.
  - Sanitizar campos de texto enriquecido.
- Esfuerzo estimado: M (1 día)

## F-15 [P2 Medio] Ausencia de rate limiting y protección anti-bruteforce
- Tipo: Vulnerabilidad
- OWASP API: API2 Broken Authentication / API4 Unrestricted Resource Consumption
- Evidencia:
  - Login sin throttling: `backend/api/routes/auth.py:14-21`
  - No middleware/limitador en código (búsqueda sin resultados de rate limiter)
- Impacto: fuerza bruta y abuso de endpoints.
- Recomendación:
  - Rate limit por IP+usuario en login y endpoints de alto coste.
  - Backoff progresivo y lockout temporal.
- Esfuerzo estimado: M (1 día)

## F-16 [P2 Medio] Consumo no restringido en endpoints/listados e importación CSV
- Tipo: Riesgo de disponibilidad
- OWASP API: API4 Unrestricted Resource Consumption
- Evidencia:
  - Listados sin paginación en varios módulos (`proposals`, `growth`, `communications`, `reports`).
  - Import CSV procesa contenido completo en memoria: `backend/api/routes/sync.py:36`.
- Impacto: degradación y riesgo de DoS por payloads grandes.
- Recomendación:
  - Paginación y límites por defecto.
  - Límite de tamaño de payload y streaming para importaciones.
- Esfuerzo estimado: M (1-2 días)

## F-17 [P2 Medio] Desalineación de permisos entre frontend y backend (finanzas)
- Tipo: Defecto de diseño
- Evidencia:
  - Frontend usa `finance_dashboard`: `frontend/src/components/layout/app-layout.tsx:29`
  - Backend no usa `finance_dashboard`; resumen financiero consume módulos finanzas concretos.
  - Seed por defecto no incluye módulos `finance_*`: `backend/db/seed.py:99-101`.
- Impacto: navegación/permisos inconsistentes y configuración confusa.
- Recomendación: normalizar catálogo de módulos y unificar contrato frontend/backend.
- Esfuerzo estimado: S-M (4-8h)

## F-18 [P2 Medio] Calidad técnica frontend comprometida (lint + tamaño bundle)
- Tipo: Calidad/mantenibilidad/performance
- Evidencia:
  - `npm run lint` falla con 19 errores (`any`, hooks, react-refresh).
  - `npm run build` reporta chunk principal ~978.75 kB.
- Impacto: mayor riesgo de regresiones y peor performance inicial.
- Recomendación:
  - Corregir lint a 0 errores.
  - Aplicar code-splitting por ruta y `manualChunks`.
- Esfuerzo estimado: M (2-4 días)

## F-19 [P3 Bajo] Validaciones débiles en esquema de invitaciones
- Tipo: Calidad/seguridad
- Evidencia:
  - `backend/schemas/invitation.py:8` (`email: str`)
  - `backend/schemas/invitation.py:9` (`role: str`)
  - `backend/schemas/invitation.py:30` (`password: str` sin límites)
- Impacto: peor validación de entrada, errores 500 por rol inválido y contraseñas débiles en flujo invitación.
- Recomendación:
  - `EmailStr`, enum de rol, validación mínima de password.
- Esfuerzo estimado: S (2-4h)

## F-20 [P3 Bajo] Tipos inconsistentes en migración (`Integer` para flags booleanos)
- Tipo: Riesgo de drift de esquema
- Evidencia:
  - `backend/db/migrations/versions/1402b443a01d_add_events_sprint_phases_and_task_inbox.py:30`
  - `backend/db/migrations/versions/1402b443a01d_add_events_sprint_phases_and_task_inbox.py:42`
- Impacto: inconsistencias entre entornos/migraciones.
- Recomendación: corregir migración de tipado y verificar estado de DB.
- Esfuerzo estimado: S (1-2h)

---

## 4) Segunda pasada de seguridad (OWASP API Top 10 - 2023)

### Resultado por categoría

| Categoría | Estado | Riesgo | Evidencia principal |
|---|---|---|---|
| API1 Broken Object Level Authorization | Fallo | Alto | `time_entries`, `communications`, `reports`, `pm` |
| API2 Broken Authentication | Parcial | Medio | sin rate limit en login, token en localStorage |
| API3 Broken Object Property Level Authorization | Fallo | Alto | `can_write` no aplicado, secretos en plano |
| API4 Unrestricted Resource Consumption | Fallo | Medio | listados sin paginación, import CSV en memoria |
| API5 Broken Function Level Authorization | Fallo | Alto | rutas sin `require_module` |
| API6 Unrestricted Access to Sensitive Business Flows | Parcial | Medio | generación masiva reportes/insights sin control de cuota |
| API7 Server Side Request Forgery | Parcial | Medio | vector contextual en generación PDF HTML->PDF |
| API8 Security Misconfiguration | Fallo | Alto | secret default, path traversal, defaults débiles |
| API9 Improper Inventory Management | Parcial | Medio | sin versionado API y contrato de permisos inconsistente |
| API10 Unsafe Consumption of APIs | Parcial | Bajo-Medio | llamadas externas sin política de allowlist ni resiliencia avanzada |

### Conclusión de segunda pasada
- La superficie de mayor riesgo está en autorización y aislamiento de datos.
- La corrección de F-01/F-02/F-03/F-04 reduce drásticamente la exposición.
- El siguiente vector relevante es endurecimiento operativo (secrets, rate limits, cuotas, observabilidad).

---

## 5) Plan de remediación por fases

## Fase 0 (0-48 horas) - Contención crítica
Objetivo: cerrar exposición inmediata.
- Corregir path traversal en fallback SPA.
- Aplicar `require_module` en rutas críticas hoy abiertas (`reports`, `proposals`, `growth`, `billing`, `time_entries`, `communications`, `task_categories`, `pm`).
- Introducir chequeo `write` en endpoints de mutación.
- Corregir `TaskStatus.todo`.
- Desactivar/rotar credenciales débiles conocidas del seed en entornos compartidos.

Criterios de salida:
- No se puede leer ningún archivo fuera de `frontend/dist`.
- Un usuario sin permiso no puede invocar módulos no autorizados.
- Generación de PM insights no rompe por enum.

## Fase 1 (Semana 1) - Modelo robusto de autorización
Objetivo: autorización coherente y testeada.
- Implementar `require_module(module, write=False)`.
- Definir mapa único `endpoint -> módulo -> scope(read/write)`.
- Añadir tests automáticos de autorización por endpoint.
- Aislar PM insights por usuario.

Criterios de salida:
- 100% endpoints funcionales mapeados a permiso.
- Tests negativos de autorización pasando.

## Fase 2 (Semana 2) - Aislamiento de datos y seguridad aplicada
Objetivo: eliminar IDOR/BOLA.
- Ownership checks en `time_entries`, `communications`, `reports`, `pm`.
- Definir política explícita: `admin`, `member`, perfiles por permiso.
- Paginación y límites en listados críticos.
- Límite de tamaño en import CSV.

Criterios de salida:
- Ningún usuario miembro accede a recursos ajenos por ID sin permiso.
- Endpoints grandes responden con paginación por defecto.

## Fase 3 (Semana 3) - Hardening operativo
Objetivo: reducir riesgo de explotación y abuso.
- Rate limit login y endpoints costosos.
- Política de secrets: fail-fast en producción si hay defaults inseguros.
- Cifrado en reposo para `ai_api_key`.
- Sanitización CSV anti-formula.
- Endurecimiento de render PDF (autoescape y recursos permitidos).

Criterios de salida:
- Controles de abuso activos.
- Secretos sensibles no almacenados en plano.

## Fase 4 (Semana 4) - Calidad y rendimiento
Objetivo: estabilidad y UX/performance.
- Corregir 19 errores de lint.
- Corregir bugs UI (project detail / inbox).
- Code-splitting por rutas + reducción de bundle inicial.
- Atacar N+1 backend y fan-out frontend.

Criterios de salida:
- `npm run lint` en verde.
- Chunk inicial dentro del objetivo (p.ej. < 400 kB minificado principal).

## Fase 5 (1-2 sprints) - Evolución de producto
Objetivo: convertir la plataforma en sistema de decisión operativo.
- Riesgo operativo automático por cliente/proyecto.
- Forecast por escenarios con alertas de runway.
- Automatización de reportes ejecutivos.
- Inbox inteligente con clasificación asistida.

---

## 6) Matriz de permisos recomendada

Nota: la app hoy usa `admin/member` + tabla `UserPermission`. Esta matriz propone perfiles objetivos reutilizando el modelo actual.

### 6.1 Convenciones
- `R` = lectura
- `W` = escritura (crear/editar/borrar)
- `-` = sin acceso

### 6.2 Matriz por perfil

| Módulo | Admin | Member Operaciones | Member Finanzas | Member Sales/CRM | Member Solo Lectura |
|---|---|---|---|---|---|
| dashboard | R/W | R/W | R | R | R |
| clients | R/W | R/W | R | R/W | R |
| projects | R/W | R/W | R | R | R |
| tasks | R/W | R/W | R | R | R |
| task_categories | R/W | R/W | R | R | R |
| timesheet | R/W | R/W (propio + equipo según política) | R | - | R |
| communications | R/W | R/W | R | R/W | R |
| proposals | R/W | R/W | R | R/W | R |
| reports | R/W | R/W | R/W (financieros) | R | R |
| growth | R/W | R/W | R | R | R |
| billing | R/W | R | R/W | R | R |
| pm | R/W | R/W (aislado por usuario) | R | R | R |
| finance_income | R/W | R | R/W | - | R |
| finance_expenses | R/W | R | R/W | - | R |
| finance_taxes | R/W | R | R/W | - | R |
| finance_forecasts | R/W | R | R/W | - | R |
| finance_advisor | R/W | R | R/W | - | R |
| finance_import | R/W | - | R/W | - | - |
| users | R/W | - | - | - | - |
| invitations/permissions | R/W | - | - | - | - |

### 6.3 Reglas técnicas obligatorias para esta matriz
- GET -> requiere `can_read`.
- POST/PUT/PATCH/DELETE -> requiere `can_write`.
- Para recursos con ownership:
  - `member`: restringido a recursos propios o del alcance asignado.
  - `admin`: acceso completo.
- Todas las rutas deben mapear explícitamente a un módulo, sin excepciones implícitas.

---

## 7) Mapa de módulos backend recomendado (endpoint -> módulo)

| Grupo de rutas | Módulo recomendado |
|---|---|
| `/api/dashboard/*` | `dashboard` |
| `/api/clients/*` | `clients` |
| `/api/projects/*` | `projects` |
| `/api/tasks/*` y `/api/task-categories/*` | `tasks` |
| `/api/time-entries/*` y `/api/timer/*` | `timesheet` |
| `/api/communications*` | `communications` |
| `/api/proposals*` | `proposals` |
| `/api/reports*` | `reports` |
| `/api/growth*` | `growth` |
| `/api/billing*` | `billing` |
| `/api/pm/*` | `pm` |
| `/api/finance/income*` | `finance_income` |
| `/api/finance/expenses*` y categorías | `finance_expenses` |
| `/api/finance/taxes*` | `finance_taxes` |
| `/api/finance/forecasts*` | `finance_forecasts` |
| `/api/finance/advisor*` | `finance_advisor` |
| `/api/finance/sync*` | `finance_import` |
| `/api/users*` | `users` (admin-only escritura) |
| `/api/invitations*` y `/api/users/{id}/permissions` | `users` (admin-only) |

---

## 8) Optimización técnica y de arquitectura

## 8.1 Backend
- Sustituir consultas N+1 por agregaciones y joins (insights/reportes).
- Estandarizar paginación en listados (límite, offset/cursor, orden estable).
- Definir políticas de caché para dashboards y reportes recurrentes.
- Añadir timeouts y circuit breaker para llamadas externas.

## 8.2 Frontend
- Dividir bundle por rutas (`React.lazy`, dynamic import).
- Extraer bloques de UI pesados a chunks separados.
- Eliminar `any` y endurecer tipos de API cliente.
- Corregir hooks con warnings (`set-state-in-effect`) para evitar renders cascada.

## 8.3 Operación
- Añadir auditoría de seguridad por evento (quién leyó/editó qué recurso sensible).
- Añadir métricas de autorización denegada y errores 401/403/5xx.
- Implementar pipeline CI mínimo: lint + build + pruebas authZ.

---

## 9) Ideas de producto (priorizadas)

## 9.1 Corto plazo (alto impacto, baja complejidad)
- Inbox inteligente que sugiera cliente/proyecto/tipo automáticamente.
- Semáforo de riesgo por cliente (rentabilidad, retraso, silencio comercial).
- Alertas de tareas sin responsable/sin fecha/sin estimación con auto-asignación sugerida.

## 9.2 Medio plazo (valor diferencial)
- Forecast financiero por escenarios (base/optimista/pesimista) con runway.
- Reportes ejecutivos automáticos semanales por cliente con acciones sugeridas.
- Sistema de salud de proyectos con score compuesto (plazo/coste/carga/engagement).

## 9.3 Largo plazo (estrategia)
- Motor de recomendaciones “next best action” por cuenta.
- Predicción de churn de clientes con señales operativas y financieras.
- Benchmark interno por tipo de servicio para pricing y capacidad.

---

## 10) Backlog de pruebas recomendado (seguridad + regresión)

## 10.1 Seguridad
- Pruebas automáticas de autorización por endpoint (matriz read/write).
- Pruebas de ownership: un usuario no puede leer/editar/borrar recurso ajeno.
- Pruebas de path traversal en rutas estáticas (`../`, `%2e%2e/`, etc.).
- Pruebas anti-abuso: rate limiting login y endpoints costosos.

## 10.2 Funcional
- Generación PM insights (incluyendo QA).
- Flujo Inbox capture -> triage -> task normal.
- Navegación desde detalle de proyecto a tareas.

## 10.3 Performance
- Presupuesto de bundle y comparación por PR.
- Benchmark de endpoints de dashboard/reportes con dataset realista.

---

## 11) Riesgos residuales si no se actúa

- Exposición de datos internos y potencial compromiso de secretos.
- Escalada de acciones no autorizadas por usuarios miembro.
- Inestabilidad operativa en módulos de PM e Inbox.
- Degradación de experiencia por deuda de frontend y carga inicial alta.

---

## 12) Estimación total de implementación (si se ejecuta todo)

- Contención crítica (Fase 0): 1-2 días.
- Hardening authZ + ownership (Fase 1-2): 1.5-2.5 semanas.
- Seguridad operativa + secretos (Fase 3): 1 semana.
- Calidad/performance (Fase 4): 1 semana.
- Evolución de producto (Fase 5): 1-2 sprints.

Total técnico recomendado inicial (sin ideas de largo plazo): **4-6 semanas** con equipo pequeño.

---

## 13) Supuestos y límites de esta auditoría

- Revisión sin cambios de código en este ciclo.
- Revisión estática y ejecución local básica de build/lint/compilación.
- No se realizó pentest dinámico completo ni DAST externo.
- No se analizaron secretos reales de entorno productivo ni infraestructura cloud viva.

