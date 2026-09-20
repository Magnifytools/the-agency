import { Navigate } from "react-router-dom"
import { useAuth } from "@/context/auth-context"
import { navigationFor } from "./navigation"

/** Start with personal work; users with fewer permissions get an accessible area. */
export function HomeRedirect() {
  const { isLoading, hasPermission, isAdmin } = useAuth()
  if (isLoading) return null
  const firstWorkSurface = navigationFor(hasPermission, isAdmin).flatMap(area => area.links).find(link => link.to !== "/incidents")
  return <Navigate to={firstWorkSurface?.to ?? "/settings"} replace />
}
