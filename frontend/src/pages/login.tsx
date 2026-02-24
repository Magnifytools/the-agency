import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
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
      navigate("/dashboard")
    } catch {
      setError("Credenciales incorrectas")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="flex items-center justify-center mb-3">
            <svg width="44" height="44" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M46.17 33.4C44.05 28.29 41.14 24.01 37.23 20.1C33.32 16.19 28.68 13.09 23.57 10.97C18.46 8.86 12.99 7.77 7.45 7.77L7.45 49.88L7.45 92C12.99 92 18.46 90.91 23.57 88.79C28.68 86.67 33.32 83.57 37.23 79.66C41.14 75.75 44.03 71.56 46.15 66.45" stroke="#FFD600" strokeWidth="2.5"/>
              <circle cx="33.61" cy="49.88" r="26.09" stroke="#F0F0F0" strokeWidth="2.5"/>
              <circle cx="65.52" cy="49.88" r="26.09" stroke="#F0F0F0" strokeWidth="2.5"/>
              <path d="M53.01 66.45C55.13 71.56 57.99 75.75 61.9 79.66C65.81 83.57 70.46 86.67 75.57 88.79C80.68 90.91 86.15 92 91.68 92L91.68 49.88L91.68 7.77C86.15 7.77 80.68 8.86 75.57 10.97C70.46 13.09 65.81 16.19 61.9 20.1C58.16 23.84 55.16 28.25 53.06 33.1" stroke="#F0F0F0" strokeWidth="2.5"/>
              <circle cx="49.57" cy="49.88" r="4.78" stroke="#FFD600" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="bevel"/>
            </svg>
          </div>
          <h1 className="text-xl font-bold tracking-tight">Magnify</h1>
          <p className="text-sm text-muted-foreground">Agency Manager</p>
        </div>
        <div className="rounded-[16px] border border-border bg-card p-8">
          <h2 className="text-lg font-semibold text-foreground mb-6">Iniciar sesión</h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="admin@agency.com"
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
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Entrando..." : "Entrar"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
