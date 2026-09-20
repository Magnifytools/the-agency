import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useAuth } from "@/context/auth-context"
import { timerApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Play, Square } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { invalidateTimeChange } from "@/lib/query-keys"
import { elapsedSeconds, formatElapsedSeconds } from "@/lib/timer"

interface TimerButtonProps {
  taskId: number
}

export function TimerButton({ taskId }: TimerButtonProps) {
  const { user, hasPermission } = useAuth()
  if (!hasPermission("timesheet") || !hasPermission("timesheet", true)) return null
  return <PermittedTimerButton key={`${user?.id}:${taskId}`} taskId={taskId} />
}

function PermittedTimerButton({ taskId }: TimerButtonProps) {
  const queryClient = useQueryClient()
  const [elapsed, setElapsed] = useState("")

  const timerQuery = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  })
  const timer = timerQuery.isError ? undefined : timerQuery.data
  const timerUnknown = (timerQuery.isPending || timerQuery.isError) && !timer

  const isThisTaskRunning = timer?.task_id === taskId

  // eslint-disable-next-line react-hooks/set-state-in-effect -- Timer tick requires setInterval in effect
  useEffect(() => {
    if (!isThisTaskRunning || !timer?.started_at) {
      setElapsed("")
      return
    }
    const updateElapsed = () => setElapsed(formatElapsedSeconds(elapsedSeconds(
      timer.started_at,
      timer.accumulated_seconds || 0,
      timer.is_paused || false,
    )))
    updateElapsed()
    if (timer.is_paused) return
    const interval = setInterval(() => {
      updateElapsed()
    }, 1000)
    return () => clearInterval(interval)
  }, [isThisTaskRunning, timer?.started_at, timer?.is_paused, timer?.accumulated_seconds])

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
      invalidateTimeChange(queryClient)
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

  if (timerUnknown) {
    if (timerQuery.isPending) {
      return <Button variant="ghost" size="icon" disabled aria-label="Comprobando el cronómetro" title="Comprobando el cronómetro"><Play className="h-4 w-4" /></Button>
    }
    return (
      <div className="flex items-center gap-1.5">
        <Button variant="ghost" size="icon" disabled aria-label="Estado del cronómetro no disponible" title="No se pudo comprobar el cronómetro">
          <Play className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void timerQuery.refetch()} disabled={timerQuery.isFetching}>
          Reintentar
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
