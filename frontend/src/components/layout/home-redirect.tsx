import { Navigate } from "react-router-dom"
import { useAuth } from "@/context/auth-context"
import { navigationFor } from "./navigation"

/** Start with personal work; users with fewer permissions get an accessible area. */
export function HomeRedirect() {
  const { isLoading, hasPermission, isAdmin } = useAuth()
  if (isLoading) return null
  return <Navigate to={navigationFor(hasPermission, isAdmin)[0]?.links[0].to ?? "/settings"} replace />
}
