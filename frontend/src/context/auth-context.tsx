import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react"
import { authApi } from "@/lib/api"
import type { User } from "@/lib/types"

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  isAdmin: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  hasPermission: (module: string, write?: boolean) => boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(() => !!localStorage.getItem("token"))

  useEffect(() => {
    const token = localStorage.getItem("token")
    if (token) {
      authApi
        .me()
        .then(setUser)
        .catch(() => localStorage.removeItem("token"))
        .finally(() => setIsLoading(false))
    }
  }, [])

  const login = async (email: string, password: string) => {
    const { access_token } = await authApi.login(email, password)
    localStorage.setItem("token", access_token)
    const me = await authApi.me()
    setUser(me)
  }

  const logout = () => {
    localStorage.removeItem("token")
    setUser(null)
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
      value={{ user, isAuthenticated: !!user, isLoading, isAdmin, login, logout, hasPermission }}
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
