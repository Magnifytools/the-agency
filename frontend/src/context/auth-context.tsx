import { createContext, useContext, useEffect, useState, useCallback, useRef, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { authApi } from "@/lib/api"
import type { User } from "@/lib/types"

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  isAdmin: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  hasPermission: (module: string, write?: boolean) => boolean
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const sessionEpoch = useRef(0)

  const clearSessionCache = useCallback(async () => {
    sessionEpoch.current += 1
    await queryClient.cancelQueries()
    queryClient.clear()
    setUser(null)
    setIsLoading(false)
  }, [queryClient])

  useEffect(() => {
    const epoch = sessionEpoch.current
    authApi
      .me()
      .then((nextUser) => {
        if (epoch === sessionEpoch.current) setUser(nextUser)
      })
      .catch(() => {
        if (epoch === sessionEpoch.current) setUser(null)
      })
      .finally(() => {
        if (epoch === sessionEpoch.current) setIsLoading(false)
      })

    // A 401 can race an older response. Cancel and remove every query first so
    // that response cannot repopulate the cache for the next identity.
    const onExpired = () => { void clearSessionCache() }
    window.addEventListener("auth:expired", onExpired)
    return () => window.removeEventListener("auth:expired", onExpired)
  }, [clearSessionCache])

  const login = async (email: string, password: string) => {
    await clearSessionCache()
    const epoch = sessionEpoch.current
    await authApi.login(email, password)
    const me = await authApi.me()
    if (epoch === sessionEpoch.current) setUser(me)
  }

  const logout = async () => {
    await clearSessionCache()
    await authApi.logout().catch(() => undefined)
  }

  const refreshUser = async () => {
    const epoch = sessionEpoch.current
    const me = await authApi.me()
    if (epoch === sessionEpoch.current) setUser(me)
  }

  const isAdmin = user?.role === "admin"

  const hasPermission = useCallback(
    (module: string, write = false): boolean => {
      if (!user) return false
      if (user.role === "admin") return true
      const perm = user.permissions?.find((p) => p.module === module)
      if (!perm) return false
      return write ? perm.can_write : perm.can_read
    },
    [user],
  )

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticated: !!user, isLoading, isAdmin, login, logout, hasPermission, refreshUser }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be inside AuthProvider")
  return ctx
}
