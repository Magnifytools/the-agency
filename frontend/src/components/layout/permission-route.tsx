import { useEffect, useRef } from "react"
import { Navigate } from "react-router-dom"
import { toast } from "sonner"
import { useAuth } from "@/context/auth-context"

interface PermissionRouteProps {
  children: React.ReactNode
  adminOnly?: boolean
  module?: string
  write?: boolean
}

/**
 * Guards a route by role or module permission.
 * Redirects to /dashboard with a toast if unauthorized.
 */
export function PermissionRoute({
  children,
  adminOnly = false,
  module,
  write = false,
}: PermissionRouteProps) {
  const { isLoading, isAdmin, hasPermission } = useAuth()
  const toastShown = useRef(false)

  const denied =
    (!isLoading && adminOnly && !isAdmin) ||
    (!isLoading && module && !hasPermission(module, write))

  useEffect(() => {
    if (denied && !toastShown.current) {
      toastShown.current = true
      toast.error("No tienes permisos para acceder a esta sección")
    }
  }, [denied])

  if (isLoading) return null

  if (denied) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}
