import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timerApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Play, Square } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

interface TimerButtonProps {
  taskId: number
}

function formatElapsed(startedAt: string): string {
  const elapsed = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000)
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

export function TimerButton({ taskId }: TimerButtonProps) {
  const queryClient = useQueryClient()
  const [elapsed, setElapsed] = useState("")

  const { data: timer } = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  })

  const isThisTaskRunning = timer?.task_id === taskId

  useEffect(() => {
    if (!isThisTaskRunning || !timer?.started_at) {
      setElapsed("")
      return
    }
    setElapsed(formatElapsed(timer.started_at))
    const interval = setInterval(() => {
      setElapsed(formatElapsed(timer.started_at))
    }, 1000)
    return () => clearInterval(interval)
  }, [isThisTaskRunning, timer?.started_at])

  const startMutation = useMutation({
    mutationFn: () => timerApi.start({ task_id: taskId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      toast.success("Timer iniciado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al iniciar timer")),
  })

  const stopMutation = useMutation({
    mutationFn: () => timerApi.stop(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      queryClient.invalidateQueries({ queryKey: ["time-entries"] })
      toast.success("Timer detenido")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al detener timer")),
  })

  if (isThisTaskRunning) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-xs font-mono text-destructive font-medium animate-pulse">
          {elapsed}
        </span>
        <Button
          variant="destructive"
          size="icon"
          onClick={() => stopMutation.mutate()}
          disabled={stopMutation.isPending}
          title="Detener timer"
        >
          <Square className="h-4 w-4" />
        </Button>
      </div>
    )
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => startMutation.mutate()}
      disabled={startMutation.isPending || (!!timer && !isThisTaskRunning)}
      title={timer ? "Detén el timer activo primero" : "Iniciar timer"}
    >
      <Play className="h-4 w-4" />
    </Button>
  )
}
