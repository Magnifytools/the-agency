import { useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { AxiosError } from "axios"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { getErrorMessage } from "@/lib/utils"

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { from, expired } = (location.state ?? {}) as { from?: string; expired?: boolean }
  // Sólo rutas internas: nada de volver a "//otro-sitio".
  const returnTo = from && from.startsWith("/") && !from.startsWith("//") && !from.startsWith("/login") ? from : "/"
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      await login(email, password)
      navigate(returnTo, { replace: true })
    } catch (err) {
      if (err instanceof AxiosError) {
        if (!err.response) {
          setError("No se pudo conectar con el servidor. Revisa tu red.")
        } else if (err.response.status === 401) {
          setError("Email o contraseña incorrectos.")
        } else if (err.response.status >= 500) {
          setError("Error interno del servidor. Intenta de nuevo.")
        } else {
          setError(getErrorMessage(err, "No se pudo iniciar sesión."))
        }
      } else {
        setError(getErrorMessage(err, "No se pudo iniciar sesión."))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center flex flex-col items-center gap-3">
          <svg width="44" height="44" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
            <rect width="100" height="100" rx="20" fill="#0A0A0A"/>
            <path d="M50 18 L74 80 L65 80 L59 63 L41 63 L35 80 L26 80 Z M50 32 L43 56 L57 56 Z" fill="#FFD600" fillRule="evenodd"/>
          </svg>
          <div>
            <p className="text-lg font-semibold text-foreground tracking-tight">The Agency</p>
            <p className="text-xs text-muted-foreground">by Magnify</p>
          </div>
        </div>
        <div className="rounded-[16px] border border-border bg-card p-8">
          <h1 className="text-lg font-semibold text-foreground mb-6">Iniciar sesión</h1>
          {expired && (
            <p role="status" className="mb-5 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              Tu sesión ha caducado. Vuelve a entrar y seguirás donde estabas.
            </p>
          )}
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="text"
                inputMode="email"
                autoComplete="email"
                placeholder="tu@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Contraseña</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Entrando..." : "Entrar"}
            </Button>
          </form>
        </div>
        <p className="mt-6 text-center text-xs text-muted-foreground">
          <Link to="/acerca" className="hover:text-foreground">Qué es The Agency</Link>
          {" · "}
          <Link to="/privacidad" className="hover:text-foreground">Privacidad</Link>
        </p>
      </div>
    </div>
  )
}
