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
        <div className="mb-8 text-center flex flex-col items-center gap-2">
          <svg height="30" viewBox="0 0 447.5208 54.6848" xmlns="http://www.w3.org/2000/svg">
            <g fill="#F0F0F0"><polygon points="63.0249 .7853 63.0249 11.9133 53.5808 11.9133 36.0752 53.8803 26.9488 53.8803 9.4441 11.9133 0 11.9133 0 .7853 14.3999 .7853 31.4371 41.3314 31.5869 41.3314 48.625 .7853 63.0249 .7853"/><rect x="53.7488" y="11.5207" width="9.2761" height="42.3597"/><rect y="11.5207" width="9.2761" height="42.3597"/><path d="M180.9396,33.9812h13.6708v19.7685c3.497-.7488,6.527-2.0017,9.2761-3.7778v-24.3125h-22.9468v8.3218ZM184.7731,0c-17.7476,0-29.1934,10.6979-29.1934,27.3424,0,16.6263,11.4458,27.3424,29.1934,27.3424.5233,0,1.0287,0,1.5337-.0192v-8.5647c-.3927.0183-.8041.0183-1.2159.0183-11.9873,0-19.8242-7.3502-19.8242-18.7768,0-11.4458,7.8369-18.7951,19.8242-18.7951,7.5931,0,13.5214,2.0757,18.3092,6.6388h.4863V4.7129c-5.0494-3.2911-11.0339-4.7129-19.1133-4.7129Z"/><path d="M266.8339.7853v39.6667h-.1498L242.1283.7853h-10.1737l6.4146,10.4733,26.1452,42.6217h11.5956V.7853h-9.2761ZM228.9251,11.5207v42.3597h9.2761v-27.2301l-9.2761-15.1296Z"/><path d="M302.0459.7853v53.095h9.5939V.7853h-9.5939Z"/><path d="M347.1512,23.7326v-14.3817l-9.5939-3.7212v48.2506h9.5939v-21.5821h23.9198v-8.5656h-23.9198ZM337.5573.7853v8.5656h39.274V.7853h-39.274Z"/><path d="M436.3371.7853l-10.8472,15.598,5.2553,7.5556L447.5208.7853h-11.1837Z"/><polygon points="425.4469 29.7733 425.4469 53.8803 415.8531 53.8803 415.8531 31.4198 393.6345 .7853 405.3049 .7853 420.8089 23.097 425.4469 29.7733"/><line x1="194.6044" y1="44.7723" x2="204.3891" y2="40.8173" stroke="#F0F0F0" strokeWidth="1"/></g>
            <g fill="#FFD600"><path d="M124.2013,17.6171h-9.5564l.9725,2.3377,6.5265,15.5414h-.0557l3.5714,8.3976.599,1.4209,3.6281,8.5656h10.3235l-16.009-36.2633Z"/><polygon points="121.5768 11.6704 111.9829 11.6704 94.2353 53.8803 84.2296 53.8803 93.0189 33.8698 107.4755 1.0292 107.5878 .7853 116.7707 .7853 120.3057 8.7903 121.5768 11.6704"/></g>
          </svg>
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
