/**
 * Módulos ocultos — la misma lista que `backend/core/modules.py`.
 *
 * Contexto (auditoría ago 2026): 279 de los 349 endpoints no recibieron una sola
 * llamada en 77 días. En vez de borrar de golpe, se ocultan: la entrada de menú
 * desaparece, la ruta redirige al dashboard y el router del backend no se
 * registra. **El código sigue en el repositorio.**
 *
 * Reactivar un módulo: quitar su clave de aquí Y de `backend/core/modules.py`.
 * Hay un test (`backend/tests/test_hidden_modules.py`) que lee este fichero y
 * falla si las dos listas divergen — para que no pase lo de siempre, que una se
 * queda atrás.
 */
export const HIDDEN_MODULES = [
  "finance", // 0 llamadas — 8 páginas
  "holded", // 26 — dos visitas en 77 días
  "cfo", // 0
  "reports", // 0 — el informe mensual se hace fuera de la app
  "proposals", // 30, solo el listado: nunca se creó una propuesta
  "leads", // 37 — Pipeline
  "growth", // 4 — Buffer de ideas
  "my_week", // 12
  "automations", // 0
  "vault", // 0
  "billing", // 0
  "capacity", // solo frontend
  "executive", // solo frontend
  "discord", // 13 — solo la pantalla de ajustes del webhook
  "communications", // 0
  "resources", // 0
  "evidence", // 0
  "core_updates", // 0
  "invitations", // 0
  "export", // 0
] as const

export type HiddenModule = (typeof HIDDEN_MODULES)[number]

const HIDDEN = new Set<string>(HIDDEN_MODULES)

/** ¿Está oculto este módulo? */
export function isHidden(module: string): boolean {
  return HIDDEN.has(module)
}

/** ¿Está visible este módulo? */
export function isEnabled(module: string): boolean {
  return !HIDDEN.has(module)
}

/**
 * Rutas del frontend que pertenecen a un módulo oculto.
 * Se usa en App.tsx para redirigir en vez de renderizar una pantalla que
 * llamaría a endpoints que ya no existen.
 */
export const HIDDEN_ROUTES: Record<string, string> = {
  "/executive": "executive",
  "/leads": "leads",
  "/pipeline": "leads",
  "/growth": "growth",
  "/my-week": "my_week",
  "/proposals": "proposals",
  "/reports": "reports",
  "/capacity": "capacity",
  "/billing": "billing",
  "/vault": "vault",
  "/automations": "automations",
  "/discord": "discord",
  "/finance": "finance",
  "/finance/cfo": "cfo",
  "/finance/income": "finance",
  "/finance/expenses": "finance",
  "/finance/taxes": "finance",
  "/finance/forecasts": "finance",
  "/finance/advisor": "finance",
  "/finance/import": "finance",
  "/finance-holded": "holded",
}
