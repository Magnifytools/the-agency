import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timerApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Square, Clock, Play } from "lucide-react"
import { toast } from "sonner"

function formatElapsed(startedAt: string): string {
  const elapsed = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000)
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

export function ActiveTimerBar() {
  const queryClient = useQueryClient()
  const [elapsed, setElapsed] = useState("")
  const [omniInput, setOmniInput] = useState("")

  const { data: timer } = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (!timer?.started_at) return
    setElapsed(formatElapsed(timer.started_at))
    const interval = setInterval(() => {
      setElapsed(formatElapsed(timer.started_at))
    }, 1000)
    return () => clearInterval(interval)
  }, [timer?.started_at])

  const startMutation = useMutation({
    mutationFn: (notes: string) => timerApi.start({ notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      setOmniInput("")
      toast.success("Timer iniciado")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Error al iniciar timer"),
  })

  const stopMutation = useMutation({
    mutationFn: () => timerApi.stop(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      queryClient.invalidateQueries({ queryKey: ["time-entries"] })
      toast.success("Timer detenido")
    },
    onError: () => toast.error("Error al detener timer"),
  })

  const handleOmniSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!omniInput.trim()) return
    startMutation.mutate(omniInput.trim())
  }

  // Si no hay timer activo, mostramos el Omni-Input de captura rápida
  if (!timer) {
    return (
      <div className="bg-card border-b px-4 py-2 flex justify-center items-center">
        <form onSubmit={handleOmniSubmit} className="flex relative w-full max-w-xl">
          <Input
            value={omniInput}
            onChange={(e) => setOmniInput(e.target.value)}
            placeholder="¿En qué estás trabajando? (ej. Estrategia Cliente X)"
            className="w-full bg-background border-muted pr-10"
          />
          <Button
            type="submit"
            size="sm"
            variant="ghost"
            disabled={!omniInput.trim() || startMutation.isPending}
            className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-brand"
          >
            <Play className="h-4 w-4" />
          </Button>
        </form>
      </div>
    )
  }

  // Si hay timer activo, mostramos la barra superior
  return (
    <div className="bg-brand text-primary-foreground px-4 py-2 flex items-center justify-between text-sm">
      <div className="flex items-center gap-3">
        <Clock className="h-4 w-4 animate-pulse" />
        <span className="font-bold uppercase tracking-wide">{timer.task_title || "Tarea sin nombre"}</span>
        {timer.client_name && (
          <span className="opacity-75">— {timer.client_name}</span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="font-mono font-bold">{elapsed}</span>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => stopMutation.mutate()}
          disabled={stopMutation.isPending}
          className="bg-primary-foreground text-brand hover:bg-primary-foreground/80"
        >
          <Square className="h-3 w-3 mr-1" /> Detener
        </Button>
      </div>
    </div>
  )
}
