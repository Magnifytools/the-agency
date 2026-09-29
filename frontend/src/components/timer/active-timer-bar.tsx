import { useEffect, useMemo, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timerApi, tasksApi, clientsApi, projectsApi, timeEntriesApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Dialog, DialogHeader, DialogTitle, DialogContent, DialogFooter } from "@/components/ui/dialog"
import { Square, Clock, Play, Plus } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import type { Task, Client, TimeEntry } from "@/lib/types"
import { invalidateTaskChange, invalidateTimeChange, projectKeys, taskKeys } from "@/lib/query-keys"
import { elapsedSeconds, formatElapsedSeconds } from "@/lib/timer"
import { useAuth } from "@/context/auth-context"
import { useBusinessDate } from "@/hooks/use-business-date"

const TIMER_OPTION_INITIAL_LIMIT = 100

function orderTimerTasks(tasks: Task[], today: string) {
  return [...tasks].sort((left, right) => {
    const rank = (task: Task) => {
      if (task.scheduled_date === today) return 0
      if (task.scheduled_date && task.scheduled_date < today) return 1
      if (!task.scheduled_date) return 2
      return 3
    }
    const rankDifference = rank(left) - rank(right)
    if (rankDifference) return rankDifference
    if (left.scheduled_date !== right.scheduled_date) {
      return (left.scheduled_date ?? "").localeCompare(right.scheduled_date ?? "")
    }
    return left.title.localeCompare(right.title, "es")
  })
}

function TimerTaskSelector({
  tasks,
  today,
  value,
  onChange,
  ariaLabel,
  emptyLabel,
  loading,
  disabled,
}: {
  tasks: Task[]
  today: string
  value: string
  onChange: (value: string) => void
  ariaLabel: string
  emptyLabel: string
  loading: boolean
  disabled: boolean
}) {
  const [search, setSearch] = useState("")
  const orderedTasks = useMemo(() => orderTimerTasks(tasks, today), [tasks, today])
  const normalizedSearch = search.trim().toLocaleLowerCase("es")
  const matches = normalizedSearch
    ? orderedTasks.filter((task) => task.title.toLocaleLowerCase("es").includes(normalizedSearch))
    : orderedTasks
  const selected = orderedTasks.find((task) => String(task.id) === value)
  const visible = normalizedSearch || orderedTasks.length <= TIMER_OPTION_INITIAL_LIMIT
    ? matches
    : matches.slice(0, TIMER_OPTION_INITIAL_LIMIT)
  const options = selected && !visible.some((task) => task.id === selected.id)
    ? [...visible, selected]
    : visible
  const needsSearch = orderedTasks.length > TIMER_OPTION_INITIAL_LIMIT

  return <div className="min-w-0 flex-1 space-y-1">
    {needsSearch && <Input
      type="search"
      aria-label={`${ariaLabel}: buscar`}
      value={search}
      onChange={(event) => setSearch(event.target.value)}
      placeholder={`Buscar entre ${orderedTasks.length} tareas…`}
      className="h-8 text-xs"
    />}
    <Select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label={ariaLabel}
      className="h-9 w-full text-xs"
      disabled={disabled || loading}
    >
      <option value="">{loading ? "Cargando tareas…" : emptyLabel}</option>
      {options.map((task) => (
        <option key={task.id} value={task.id}>
          {task.title.length > 50 ? `${task.title.slice(0, 50)}…` : task.title}
        </option>
      ))}
    </Select>
    {needsSearch && !normalizedSearch && <p className="text-xs text-muted-foreground">Mostramos las 100 tareas prioritarias. Busca por nombre para ver las demás.</p>}
    {normalizedSearch && options.length === 0 && <p className="text-xs text-muted-foreground">No hay tareas que coincidan.</p>}
  </div>
}

export function ActiveTimerBar() {
  const { user, hasPermission } = useAuth()
  if (!hasPermission("timesheet") || !hasPermission("timesheet", true)) return null
  return <TimerBar key={user?.id} />
}

function TimerBar() {
  const { hasPermission } = useAuth()
  const canReadTasks = hasPermission("tasks")
  const canReadClients = hasPermission("clients")
  const canReadProjects = hasPermission("projects")
  const canCreateTask = canReadClients && hasPermission("tasks", true)
  const queryClient = useQueryClient()
  const [elapsed, setElapsed] = useState("")
  const [omniInput, setOmniInput] = useState("")
  const [selectedTaskId, setSelectedTaskId] = useState<string>("")
  const [recentlyCreatedTask, setRecentlyCreatedTask] = useState<Task | null>(null)
  const [reminderShown, setReminderShown] = useState(false)
  const businessToday = useBusinessDate()

  // Post-stop assignment dialog
  const [showAssignDialog, setShowAssignDialog] = useState(false)
  const [stoppedEntryId, setStoppedEntryId] = useState<number | null>(null)
  const [assignTaskId, setAssignTaskId] = useState<string>("")

  // Quick create task
  const [showQuickCreate, setShowQuickCreate] = useState(false)
  const [qcTitle, setQcTitle] = useState("")
  const [qcClientId, setQcClientId] = useState<string>("")
  const [qcProjectId, setQcProjectId] = useState<string>("")

  const timerQuery = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    // El QueryClient global trae refetchOnWindowFocus:false. Combinado con el
    // no-refetch en segundo plano, una pestaña olvidada seguía enseñando un
    // timer que el servidor ya había parado (p. ej. porque se arrancó otro
    // desde la extensión): al volver y darle a Parar, 404. Para este dato en
    // concreto la frescura al recuperar el foco no es opcional.
    refetchOnWindowFocus: true,
  })
  const timer = timerQuery.isError ? undefined : timerQuery.data
  const timerUnknown = (timerQuery.isPending || timerQuery.isError) && !timer

  // Cualquier fallo de una acción de timer significa que la barra ya no
  // refleja el estado real del servidor: refrescarla antes de avisar.
  const resyncTimer = () => queryClient.invalidateQueries({ queryKey: ["active-timer"] })

  // Fetch user's tasks for selector
  const tasksQuery = useQuery({
    queryKey: taskKeys.assigned("timer", "me", "assigned_or_created", businessToday),
    enabled: canReadTasks,
    queryFn: () => tasksApi.listAll({
      assigned_to: "me",
      timer_scope: "assigned_or_created",
      status: "backlog,pending,in_progress,advanced,waiting,in_review",
      is_recurring: false,
      timer_eligible: true,
    }),
  })
  const tasks = !canReadTasks || tasksQuery.isError ? [] : (tasksQuery.data ?? [])
  const selectableTasks = canReadTasks && recentlyCreatedTask && !tasks.some((task) => task.id === recentlyCreatedTask.id)
    ? [recentlyCreatedTask, ...tasks]
    : tasks

  useEffect(() => {
    if (canReadTasks) return
    // Preserve a typed unlinked note, but discard task IDs that are no longer readable.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelectedTaskId("")
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRecentlyCreatedTask(null)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAssignTaskId("")
  }, [canReadTasks])

  // Fetch clients for quick create
  const clientsQuery = useQuery<Client[]>({
    queryKey: ["clients-active"],
    enabled: showQuickCreate && canCreateTask,
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
  })
  const clients = !canCreateTask || clientsQuery.isError ? [] : (clientsQuery.data ?? [])

  // Fetch active projects for the selected client (drives the Proyecto select)
  const qcClientIdNum = qcClientId ? parseInt(qcClientId, 10) : undefined
  const qcProjectsQuery = useQuery({
    queryKey: projectKeys.list(["active", "client", qcClientIdNum]),
    queryFn: () => projectsApi.listAll({ client_id: qcClientIdNum, status: "active" }),
    enabled: !!qcClientIdNum && showQuickCreate && canReadProjects,
    staleTime: 30_000,
  })
  const qcProjects = !canReadProjects || qcProjectsQuery.isError ? [] : (qcProjectsQuery.data ?? [])

  // Auto-preselect when client has exactly one active project; clear when it has none/multiple
  const singleProjectId = useMemo(
    () => (qcProjects.length === 1 ? String(qcProjects[0].id) : ""),
    [qcProjects]
  )
  useEffect(() => {
    if (!qcClientIdNum) {
      setQcProjectId("")
      return
    }
    if (qcProjects.length === 1) {
      setQcProjectId(String(qcProjects[0].id))
    } else if (qcProjects.length === 0) {
      setQcProjectId("")
    }
    // If multiple, keep current selection (user picks)
  }, [qcClientIdNum, qcProjects, singleProjectId])

  // eslint-disable-next-line react-hooks/set-state-in-effect -- Timer tick requires setInterval in effect
  useEffect(() => {
    if (!timer?.started_at) return
    const acc = timer.accumulated_seconds || 0
    const paused = timer.is_paused || false
    setElapsed(formatElapsedSeconds(elapsedSeconds(timer.started_at, acc, paused)))
    if (paused) return // Don't tick when paused
    const interval = setInterval(() => {
      setElapsed(formatElapsedSeconds(elapsedSeconds(timer.started_at, acc, false)))
    }, 1000)
    return () => clearInterval(interval)
  }, [timer?.started_at, timer?.is_paused, timer?.accumulated_seconds])

  // eslint-disable-next-line react-hooks/set-state-in-effect -- Reminder state tracks async 4h threshold
  useEffect(() => {
    if (!timer?.started_at) {
      setReminderShown(false)
      return
    }
    const check = () => {
      const secs = elapsedSeconds(
        timer.started_at,
        timer.accumulated_seconds || 0,
        timer.is_paused || false,
      )
      if (secs > 14400 && !reminderShown) {
        toast.warning("¡Llevas más de 4 horas con el timer activo! ¿Sigue corriendo?")
        setReminderShown(true)
      }
    }
    check()
    const interval = setInterval(check, 60_000)
    return () => clearInterval(interval)
  }, [timer?.started_at, timer?.accumulated_seconds, timer?.is_paused, reminderShown])

  const startMutation = useMutation({
    mutationFn: (data: { task_id?: number; notes?: string }) => timerApi.start(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      setOmniInput("")
      setSelectedTaskId("")
      setRecentlyCreatedTask(null)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al iniciar timer")),
  })

  const stopMutation = useMutation({
    mutationFn: (timerId: number) => timerApi.stop(timerId),
    onSuccess: (entry: TimeEntry) => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      invalidateTimeChange(queryClient)
      if (!entry.task_id) {
        setStoppedEntryId(entry.id)
        setAssignTaskId("")
        setShowAssignDialog(true)
        toast.success("Timer detenido — asigna una tarea al registro")
      } else {
        toast.success("Timer detenido")
      }
    },
    onError: (err) => {
      resyncTimer()
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        // Intención cumplida: no hay nada corriendo. No es un fallo del usuario.
        toast.info("Ese timer ya estaba parado", {
          description: "La barra estaba desactualizada; ya se ha refrescado.",
        })
        return
      }
      toast.error(getErrorMessage(err, "Error al detener timer"))
    },
  })

  const pauseMutation = useMutation({
    mutationFn: () => timerApi.pause(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
    },
    onError: (err) => {
      resyncTimer()
      toast.error(getErrorMessage(err, "Error al pausar"))
    },
  })

  const resumeMutation = useMutation({
    mutationFn: () => timerApi.resume(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
    },
    onError: (err) => {
      resyncTimer()
      toast.error(getErrorMessage(err, "Error al reanudar"))
    },
  })

  // Assign task to stopped entry
  const assignMutation = useMutation({
    mutationFn: (data: { entryId: number; taskId: number }) =>
      timeEntriesApi.update(data.entryId, { task_id: data.taskId }),
    onSuccess: () => {
      invalidateTimeChange(queryClient)
      setShowAssignDialog(false)
      setStoppedEntryId(null)
      toast.success("Tarea asignada al registro")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al asignar")),
  })

  // Quick create task
  const createTaskMutation = useMutation({
    mutationFn: (data: { title: string; client_id: number; project_id?: number }) =>
      tasksApi.create({
        title: data.title,
        client_id: data.client_id,
        project_id: data.project_id ?? null,
        status: "in_progress",
      }),
    onSuccess: (task: Task) => {
      invalidateTaskChange(queryClient, { projectId: task.project_id, clientId: task.client_id })
      setRecentlyCreatedTask(task)
      setSelectedTaskId(String(task.id))
      setShowQuickCreate(false)
      setQcTitle("")
      setQcClientId("")
      setQcProjectId("")
      toast.success("Tarea creada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear tarea")),
  })

  const handleOmniSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const notes = omniInput.trim() || undefined
    const task_id = canReadTasks && !tasksQuery.isError && selectedTaskId ? parseInt(selectedTaskId, 10) : undefined
    if (!notes && !task_id) return
    startMutation.mutate({ task_id, notes })
  }

  // Si no hay timer activo, mostramos el Omni-Input de captura rápida
  if (timerUnknown) {
    if (timerQuery.isPending) {
      return <div role="status" className="border-b bg-card px-4 py-2 text-center text-sm">Comprobando el cronómetro…</div>
    }
    return (
      <div role="alert" className="flex flex-wrap items-center justify-center gap-2 border-b bg-card px-4 py-2 text-sm">
        <span>No se pudo comprobar el cronómetro. Espera a actualizarlo antes de iniciar otro.</span>
        <Button variant="outline" size="sm" onClick={() => void timerQuery.refetch()} disabled={timerQuery.isFetching}>Reintentar</Button>
      </div>
    )
  }

  if (!timer) {
    return (
      <>
        <div className="bg-card border-b px-4 py-2 flex justify-center items-center">
          <form onSubmit={handleOmniSubmit} className="flex items-center gap-2 w-full max-w-2xl">
            {canReadTasks && tasksQuery.isError && <span role="alert" className="sr-only">No se pudieron cargar las tareas del cronómetro.</span>}
            <div className="w-36 shrink-0 sm:w-48">
              <TimerTaskSelector
                tasks={selectableTasks}
                today={businessToday}
                value={selectedTaskId}
                onChange={setSelectedTaskId}
                ariaLabel="Tarea del cronómetro"
                emptyLabel="Sin tarea"
                loading={tasksQuery.isLoading}
                disabled={!canReadTasks || tasksQuery.isError}
              />
            </div>
            <button
              type="button"
              onClick={() => setShowQuickCreate(true)}
              className="shrink-0 p-1.5 text-muted-foreground hover:text-brand transition-colors rounded"
              title="Crear tarea rápida. El cronómetro seguirá detenido."
              aria-label="Crear tarea rápida"
              disabled={!canCreateTask}
            >
              <Plus className="h-4 w-4" />
            </button>
            <div className="relative flex-1 min-w-0">
              <Input
                value={omniInput}
                onChange={(e) => setOmniInput(e.target.value)}
                placeholder="¿En qué estás trabajando?"
                aria-label="Describe el trabajo que vas a registrar"
                className="w-full bg-background border-muted pr-10 h-9 text-sm"
              />
              <Button
                type="submit"
                aria-label="Iniciar cronómetro"
                size="sm"
                variant="ghost"
                disabled={(!omniInput.trim() && !selectedTaskId) || startMutation.isPending}
                className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-brand"
              >
                <Play className="h-4 w-4" />
              </Button>
            </div>
          </form>
        </div>

        {/* Quick Create Task Dialog */}
        <Dialog open={showQuickCreate} onOpenChange={setShowQuickCreate}>
          <DialogHeader>
            <DialogTitle>Crear tarea rápida</DialogTitle>
          </DialogHeader>
          <DialogContent>
            <p className="text-sm text-muted-foreground">Crea una tarea para organizarla después. El cronómetro seguirá detenido.</p>
            <div>
              <label htmlFor="timer-quick-create-title" className="text-sm text-muted-foreground mb-1 block">Título *</label>
              <Input
                id="timer-quick-create-title"
                value={qcTitle}
                onChange={(e) => setQcTitle(e.target.value)}
                placeholder="Nombre de la tarea"
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="timer-quick-create-client" className="text-sm text-muted-foreground mb-1 block">Cliente *</label>
              <Select id="timer-quick-create-client" value={qcClientId} onChange={(e) => setQcClientId(e.target.value)}>
                <option value="">Selecciona cliente</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
            {qcClientId && (
              <div>
                <label htmlFor="timer-quick-create-project" className="text-sm text-muted-foreground mb-1 block">
                  Proyecto
                  {qcProjects.length === 0 && (
                    <span className="ml-1 text-xs text-muted-foreground/70">
                      (este cliente no tiene proyectos activos)
                    </span>
                  )}
                  {qcProjects.length > 1 && (
                    <span className="ml-1 text-xs text-amber-500">*</span>
                  )}
                </label>
                <Select
                  id="timer-quick-create-project"
                  value={qcProjectId}
                  onChange={(e) => setQcProjectId(e.target.value)}
                  disabled={qcProjects.length === 0}
                >
                  <option value="">
                    {qcProjects.length === 0 ? "—" : "Selecciona proyecto"}
                  </option>
                  {qcProjects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                {qcProjects.length > 1 && !qcProjectId && (
                  <p className="text-xs text-amber-500 mt-1">
                    Elige un proyecto para que el tiempo cuente en sus métricas.
                  </p>
                )}
              </div>
            )}
          </DialogContent>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowQuickCreate(false)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                if (!canCreateTask) return
                if (!qcTitle.trim() || !qcClientId) {
                  toast.error("Título y cliente son obligatorios")
                  return
                }
                if (qcProjects.length > 1 && !qcProjectId) {
                  toast.error("Elige un proyecto (el cliente tiene varios activos)")
                  return
                }
                createTaskMutation.mutate({
                  title: qcTitle.trim(),
                  client_id: parseInt(qcClientId, 10),
                  project_id: canReadProjects && qcProjectId ? parseInt(qcProjectId, 10) : undefined,
                })
              }}
              disabled={!canCreateTask || createTaskMutation.isPending}
            >
              {createTaskMutation.isPending ? "Creando..." : "Crear"}
            </Button>
          </DialogFooter>
        </Dialog>
      </>
    )
  }

  // Si hay timer activo, mostramos la barra superior
  return (
    <>
      <div className="bg-brand text-primary-foreground px-4 py-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-sm">
        <span role="status" className="sr-only">{timer.is_paused ? "Cronómetro en pausa" : "Cronómetro en marcha"}</span>
        <div className="flex min-w-0 items-center gap-2">
          <Clock className="h-4 w-4 shrink-0" />
          <span className="font-semibold truncate" title={timer.task_title || "Tarea sin nombre"}>{timer.task_title || "Tarea sin nombre"}</span>
          {timer.client_name && (
            <span className="hidden md:inline opacity-75 truncate">— {timer.client_name}</span>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 shrink-0">
          <span className="font-mono font-bold mr-auto sm:mr-0" aria-label="Tiempo del cronómetro">
            {timer?.is_paused ? "⏸ " : ""}{elapsed}
          </span>
          {timer?.is_paused ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => resumeMutation.mutate()}
              disabled={resumeMutation.isPending}
              className="bg-background text-foreground hover:bg-background/90 font-semibold min-h-9"
            >
              <Play className="h-3 w-3 mr-1" /> Reanudar
            </Button>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => pauseMutation.mutate()}
              disabled={pauseMutation.isPending}
              className="bg-background text-foreground hover:bg-background/90 font-semibold min-h-9"
            >
              ⏸ Pausa
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
              onClick={() => stopMutation.mutate(timer.id)}
            disabled={stopMutation.isPending}
            className="bg-background text-foreground hover:bg-background/90 font-semibold min-h-9"
          >
            <Square className="h-3 w-3 mr-1" /> Detener
          </Button>
        </div>
      </div>

      {/* Post-stop Assignment Dialog */}
      <Dialog open={showAssignDialog} onOpenChange={(open) => {
        if (!open) {
          setShowAssignDialog(false)
          setStoppedEntryId(null)
        }
      }}>
        <DialogHeader>
          <DialogTitle>Asignar registro a tarea</DialogTitle>
        </DialogHeader>
        <DialogContent>
          <p className="text-sm text-muted-foreground">
            El tiempo registrado no tiene tarea asignada. Selecciona una para incluirlo en sus métricas. Si lo guardas sin asignar, podrás asociarlo más tarde.
          </p>
          {canReadTasks && !tasksQuery.isError ? <TimerTaskSelector
            tasks={selectableTasks}
            today={businessToday}
            value={assignTaskId}
            onChange={setAssignTaskId}
            ariaLabel="Tarea para asignar el registro"
            emptyLabel="Selecciona tarea"
            loading={tasksQuery.isLoading}
            disabled={false}
          /> : <p role="alert" className="text-sm text-muted-foreground">No se pudieron cargar las tareas disponibles para asignar este registro.</p>}
        </DialogContent>
        <DialogFooter>
          <Button variant="ghost" onClick={() => { setShowAssignDialog(false); setStoppedEntryId(null) }}>
            Guardar sin asignar
          </Button>
          {canReadTasks && !tasksQuery.isError && <Button
            onClick={() => {
              if (assignTaskId && stoppedEntryId) {
                assignMutation.mutate({ entryId: stoppedEntryId, taskId: parseInt(assignTaskId, 10) })
              }
            }}
            disabled={!assignTaskId || tasksQuery.isLoading || assignMutation.isPending}
          >
            {assignMutation.isPending ? "Asignando..." : "Asignar"}
          </Button>}
        </DialogFooter>
      </Dialog>
    </>
  )
}
