import { Navigate } from "react-router-dom"
import { useAuth } from "@/context/auth-context"

interface PermissionRouteProps {
  children: React.ReactNode
  adminOnly?: boolean
  module?: string
  write?: boolean
}

/**
 * Guards a route by role or module permission.
 * Redirects to /dashboard if unauthorized.
 */
export function PermissionRoute({
  children,
  adminOnly = false,
  module,
  write = false,
}: PermissionRouteProps) {
  const { isLoading, isAdmin, hasPermission } = useAuth()

  if (isLoading) return null

  if (adminOnly && !isAdmin) {
    return <Navigate to="/dashboard" replace />
  }

  if (module && !hasPermission(module, write)) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}
