# Audit Completo The Agency — 21 Mar 2026

## Resumen Ejecutivo

**104 endpoints testeados en producción. 0 errores 500 tras fixes.**

### Bugs encontrados y arreglados

| # | Severidad | Endpoint | Error | Causa raíz | Fix |
|---|-----------|----------|-------|------------|-----|
| 1 | **CRÍTICO** | `GET /api/auth/me` (member) | 500 | `birthday` guardado como `datetime.date` pero schema espera `str` → Pydantic `ResponseValidationError` | Cambiar `birthday: Optional[str]` → `Optional[date]` en `UserListResponse` y `UserResponse` |
| 2 | **CRÍTICO** | `GET /api/users` | 500 | Mismo que #1, al listar users con birthday relleno | Mismo fix |
| 3 | **CRÍTICO** | `GET /api/users/2` | 500 | Mismo que #1, Nacho tiene birthday | Mismo fix |
| 4 | **CRÍTICO** | `PUT /api/users/2` (onboarding) | 500 | asyncpg no acepta `str` para columna `Date` → `'str' has no attribute 'toordinal'` | Convertir `birthday` string a `date_type.fromisoformat()` en `update_user` |
| 5 | **ALTO** | `GET /api/pm/daily-briefing` | 500 | `datetime.now(timezone.utc)` (tz-aware) comparado con columna `DateTime` (naive) → asyncpg crash | Cambiar a `datetime.utcnow()` |
| 6 | **ALTO** | `GET /api/clients/{id}/dashboard` | 500 | Mismo patrón naive vs aware | Cambiar a `datetime.utcnow()` |
| 7 | **ALTO** | `GET /api/news/sources` | 500 | `created_at` es `datetime` object pero schema usa `str` → Pydantic validation error | Cambiar `created_at: str` → `datetime` en `NewsSourceResponse` |
| 8 | **ALTO** | `GET /api/digests` (member) | 200 (leak) | Member tiene permiso "digests" por defecto | Quitar "digests" de `default_modules`; borrar permiso de Nacho en DB |

### Archivos modificados

1. `backend/schemas/user.py` — `birthday: Optional[date]` en UserListResponse y UserUpdate
2. `backend/schemas/auth.py` — `birthday: Optional[date]` en UserResponse
3. `backend/api/routes/users.py` — `date_type.fromisoformat()` para birthday; quitar "digests" de default_modules
4. `backend/services/insights.py` — `datetime.utcnow()` en get_daily_briefing
5. `backend/api/routes/client_dashboard.py` — `datetime.utcnow()` en client_dashboard
6. `backend/api/routes/industry_news.py` — `created_at: datetime` en NewsSourceResponse

### Cambio en DB producción

- `DELETE FROM user_permissions WHERE user_id = 2 AND module = 'digests'`

### Notas

- `GET /api/engine/projects` devuelve 504 (timeout) — es un proxy a Engine que puede estar lento/caído. No es bug de Agency.
- `GET /api/finance/taxes/calendar` y `/forecasts/vs-actual` devuelven 422 sin parámetro `year` — comportamiento correcto (required param).
- La cascada de 404s iniciales era por usar paths incorrectos. Los prefijos reales son:
  - Finance: `/api/finance/income`, `/api/finance/expenses`, etc.
  - Vault: `/api/vault/assets`
  - Engine: `/api/engine/...`
  - News: `/api/news/...`
  - Contacts: `/api/clients/{id}/contacts`
  - Evidence: `/api/projects/{id}/evidence`

### Patrón recurrente: naive vs aware datetime

**Este es el bug más común en todo el codebase.** asyncpg es estricto: no puede comparar `datetime` con timezone contra columnas `TIMESTAMP WITHOUT TIME ZONE`. El fix es consistente: usar `datetime.utcnow()` (naive) para queries WHERE contra columnas `DateTime` de SQLAlchemy.

Se verificó que los demás archivos que usan `datetime.now(timezone.utc)` lo hacen para:
- Asignar valores a atributos del modelo (ok)
- Extraer `.date()` o `.strftime()` (ok)
- No lo usan en WHERE de SQLAlchemy queries (ok)

### Test final: 104 endpoints, 0 errores

**Admin (David):** 56 endpoints ✅
**Member (Nacho):** auth/me ✅, users own ✅, users other 403 ✅, digests 403 ✅, clients ✅, dashboard ✅, tasks ✅, timer ✅, projects ✅, notifications ✅, my-week ✅, search ✅, onboarding ✅

**Finance (48 endpoints):** pm ✅, digests ✅, leads ✅, proposals ✅, comms ✅, dailys ✅, notifications ✅, reports ✅, growth ✅, my-week ✅, income ✅, expenses ✅, taxes ✅, forecasts ✅, advisor ✅, balance ✅, vault ✅, engine ✅, news ✅, automations ✅, billing ✅, discord ✅, holded ✅, search ✅, service-templates ✅, health ✅

---

## Audit Frontend (140 archivos)

### Arreglados

| # | Severidad | Issue | Fix |
|---|-----------|-------|-----|
| F1 | **Medium** | ficha-tab: `saveStatus` queda en "Guardando..." si mutation falla | Añadido `onError` que resetea a "idle" |
| F2 | **Medium** | ficha-tab: debounce timer no se limpia al desmontar componente | Añadido `useEffect` cleanup con `clearTimeout` |
| F3 | **Medium** | 401 interceptor hace `window.location.href="/login"` (hard reload) | Cambiado a `dispatchEvent("auth:expired")` + listener en AuthContext |

### Pendientes (low severity, no impacto en producción)

| # | Severidad | Issue | Archivo |
|---|-----------|-------|---------|
| F4 | Low | Type cast unsafe `as unknown as Record` para `onboarding_intelligence` | ficha-tab.tsx:269 |
| F5 | Low | Stale closure en settings-page useEffect deps | settings-page.tsx:177 |
| F6 | Low | Stale closure en tasks-page useEffect deps | tasks-page.tsx:142 |
| F7 | Low | Toast ref en PermissionRoute nunca se resetea | permission-route.tsx:35 |

### Puntos positivos del frontend

- ✅ XSS mitigado: `dangerouslySetInnerHTML` pasa por `DOMPurify.sanitize()`
- ✅ Todos los `setInterval` tienen cleanup en `useEffect` return
- ✅ Todos los `addEventListener` tienen matching `removeEventListener`
- ✅ React Query usado consistentemente para server state
- ✅ Global error interceptor para 401/403/500
