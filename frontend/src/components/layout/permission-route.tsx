import { useAuth } from "@/context/auth-context"
import { AccessDenied } from "@/components/layout/access-denied"

interface PermissionRouteProps {
  children: React.ReactNode
  adminOnly?: boolean
  module?: string
  write?: boolean
}

/**
 * Guards a route by role or module permission.
 * Shows an AccessDenied page in-place if unauthorized (no silent redirect).
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
    return <AccessDenied />
  }

  if (module && !hasPermission(module, write)) {
    return <AccessDenied />
  }

  return <>{children}</>
}
