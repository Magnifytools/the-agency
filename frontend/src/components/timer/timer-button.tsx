import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timerApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Play, Square } from "lucide-react"
import { toast } from "sonner"

interface TimerButtonProps {
  taskId: number
}

export function TimerButton({ taskId }: TimerButtonProps) {
  const queryClient = useQueryClient()

  const { data: timer } = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    refetchInterval: 30_000,
  })

  const isThisTaskRunning = timer?.task_id === taskId

  const startMutation = useMutation({
    mutationFn: () => timerApi.start({ task_id: taskId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      toast.success("Timer iniciado")
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || "Error al iniciar timer"
      toast.error(msg)
    },
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

  if (isThisTaskRunning) {
    return (
      <Button
        variant="destructive"
        size="icon"
        onClick={() => stopMutation.mutate()}
        disabled={stopMutation.isPending}
        title="Detener timer"
      >
        <Square className="h-4 w-4" />
      </Button>
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
