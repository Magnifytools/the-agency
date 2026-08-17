import { Navigate, useLocation } from "react-router-dom"
import { HIDDEN_ROUTES, isHidden } from "@/lib/hidden-modules"

/**
 * Redirige al dashboard cualquier ruta que pertenezca a un módulo oculto.
 *
 * Un módulo oculto no tiene routers en el backend, así que su pantalla llamaría
 * a endpoints que ya no existen y se quedaría en un error. Mejor no llegar a
 * renderizarla.
 *
 * Es UN guardián para todas las rutas, no un envoltorio por ruta, justamente
 * para que no pueda desincronizarse: la lista vive en `lib/hidden-modules.ts` y
 * aquí solo se consulta. Al reactivar un módulo, su ruta vuelve sola.
 *
 * Se envuelve por dentro del layout para que la redirección conserve la shell y
 * no parpadee.
 */
export function HiddenModuleGate({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()

  // Coincidencia por prefijo más largo: `/leads/42` cae en `/leads`, y
  // `/finance/cfo` gana a `/finance` (importa si algún día uno se reactiva
  // sin el otro).
  const match = Object.keys(HIDDEN_ROUTES)
    .filter((route) => pathname === route || pathname.startsWith(`${route}/`))
    .sort((a, b) => b.length - a.length)[0]

  if (match && isHidden(HIDDEN_ROUTES[match])) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}
