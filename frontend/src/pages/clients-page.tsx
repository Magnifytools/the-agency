import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { clientsApi, clientHealthApi, engineApi } from "@/lib/api"
import type { Client, ClientCohort, ClientContactCreate, ClientCreate, ClientExtract, ClientOnboardingCreate, ClientOnboardingResult, ClientOnboardingProjectCreate, ClientStatus, ClientHealthScore } from "@/lib/types"
import { usePagination } from "@/hooks/use-pagination"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Pencil, MoreVertical, Users, Loader2, ExternalLink, Sparkles, Upload } from "lucide-react"
import { useAuth } from "@/context/auth-context"
import { useTableSort } from "@/hooks/use-table-sort"
import { useBulkSelect } from "@/hooks/use-bulk-select"
import { SortableTableHead } from "@/components/ui/sortable-table-head"
import { InfoTooltip } from "@/components/ui/tooltip"
import { BulkActionBar } from "@/components/ui/bulk-action-bar"
import { EmptyTableState } from "@/components/ui/empty-state"
import { SkeletonTableRow } from "@/components/ui/skeleton"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { formatCurrency } from "@/lib/format"
import { clientKeys, invalidateClientChange } from "@/lib/query-keys"
import { clientHealthPresentation } from "@/components/dashboard/client-health-presentation"

const STATUS_TABS: { label: string; value: ClientStatus | "all" }[] = [
  { label: "En cartera", value: "all" },
  { label: "Activos", value: "active" },
  { label: "Pausados", value: "paused" },
  { label: "Finalizados", value: "finished" },
]

const COHORTS: { label: string; value: ClientCohort }[] = [
  { label: "Todos", value: "all" },
  { label: "Externos", value: "external" },
  { label: "Internos", value: "internal" },
]

const onboardingStoragePrefix = (userId: number) => `agency:client-onboarding:${userId}:`
const requestKeyPattern = /^[A-Za-z0-9_-]{16,64}$/

function readOnboardingKeys(userId: number) {
  try {
    const prefix = onboardingStoragePrefix(userId)
    const keys: string[] = []
    for (let index = 0; index < localStorage.length; index += 1) {
      const storageKey = localStorage.key(index)
      if (!storageKey?.startsWith(prefix)) continue
      const requestKey = storageKey.slice(prefix.length)
      if (requestKeyPattern.test(requestKey) && localStorage.getItem(storageKey) === "pending") keys.push(requestKey)
    }
    return { keys, failed: false }
  } catch {
    return { keys: [], failed: true }
  }
}

function persistOnboardingKey(userId: number, key: string) {
  try {
    localStorage.setItem(`${onboardingStoragePrefix(userId)}${key}`, "pending")
    return true
  } catch {
    return false
  }
}

function clearOnboardingKey(userId: number, key: string) {
  try {
    localStorage.removeItem(`${onboardingStoragePrefix(userId)}${key}`)
  } catch {
    // The key may be gone already. This must not keep a confirmed attempt blocked.
  }
}

function newRequestKey() {
  return crypto.randomUUID()
}

function onboardingErrorMessage(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => typeof item === "object" && item !== null && "msg" in item && typeof item.msg === "string" ? [item.msg] : [])
    if (messages.length) return messages.join(", ")
  }
  if (typeof detail === "string") return detail
  return getErrorMessage(error, "El alta no pasó la validación. Revisa los datos.")
}

const statusBadge = (status: ClientStatus) => {
  const map: Record<ClientStatus, { label: string; variant: "success" | "warning" | "secondary" }> = {
    active: { label: "Activo", variant: "success" },
    paused: { label: "Pausado", variant: "warning" },
    finished: { label: "Finalizado", variant: "secondary" },
  }
  const { label, variant } = map[status]
  return <Badge variant={variant}>{label}</Badge>
}

export default function ClientsPage() {
  const { user } = useAuth()
  return <ClientsPageBody key={user?.id ?? "anonymous"} />
}

function ClientsPageBody() {
  const queryClient = useQueryClient()
  const { isAdmin, user, hasPermission } = useAuth()
  const userId = user?.id
  const canWriteClients = hasPermission("clients", true)
  const canWriteProjects = hasPermission("projects", true)
  const { page, pageSize, setPage, reset } = usePagination(25)
  const [tab, setTab] = useState<ClientStatus | "all">("all")
  const [cohort, setCohort] = useState<ClientCohort>("all")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Client | null>(null)
  const [prefill, setPrefill] = useState<ClientExtract | null>(null)
  const [includeProject, setIncludeProject] = useState(true)
  const [formKey, setFormKey] = useState(0)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [hardDeleteId, setHardDeleteId] = useState<number | null>(null)
  const [openMenuId, setOpenMenuId] = useState<number | null>(null)
  const [bulkStatus, setBulkStatus] = useState("")
  const [onboardingKeys, setOnboardingKeys] = useState<string[]>(() => userId ? readOnboardingKeys(userId).keys : [])
  const [storageReadFailed, setStorageReadFailed] = useState(() => userId ? readOnboardingKeys(userId).failed : false)
  const onboardingKey = onboardingKeys[0] ?? null
  const [recoveringOnboarding, setRecoveringOnboarding] = useState(() => Boolean(userId && readOnboardingKeys(userId).keys.length))
  const [onboardingNotice, setOnboardingNotice] = useState<string | null>(null)
  const [onboardingError, setOnboardingError] = useState<string | null>(null)

  useEffect(() => {
    const stored = userId ? readOnboardingKeys(userId) : { keys: [], failed: false }
    setOnboardingKeys(stored.keys)
    setStorageReadFailed(stored.failed)
    setRecoveringOnboarding(stored.keys.length > 0)
    setOnboardingNotice(null)
    setOnboardingError(null)
  }, [userId])

  useEffect(() => {
    if (!userId) return
    const prefix = onboardingStoragePrefix(userId)
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea !== localStorage || !event.key?.startsWith(prefix)) return
      const stored = readOnboardingKeys(userId)
      setOnboardingKeys(stored.keys)
      setStorageReadFailed(stored.failed)
    }
    window.addEventListener("storage", onStorage)
    return () => window.removeEventListener("storage", onStorage)
  }, [userId])

  const { data: engineConfig } = useQuery({
    queryKey: ["engine-config"],
    queryFn: () => engineApi.getConfig(),
    staleTime: 10 * 60_000,
  })

  const clientsQuery = useQuery({
    queryKey: [...clientKeys.all(), tab, cohort, page, pageSize],
    queryFn: () => clientsApi.list({ status: tab === "all" ? undefined : tab, cohort, page, page_size: pageSize }),
  })
  const clientsDenied = [401, 403].includes((clientsQuery.error as { response?: { status?: number } } | null)?.response?.status ?? 0)
  const data = clientsQuery.isError ? undefined : clientsQuery.data
  const isLoading = clientsQuery.isLoading
  const clients = data?.items ?? []

  const healthQuery = useQuery({
    queryKey: ["client-health-scores", cohort],
    queryFn: () => clientHealthApi.list(cohort),
    staleTime: 60_000,
  })
  const healthDenied = [401, 403].includes((healthQuery.error as { response?: { status?: number } } | null)?.response?.status ?? 0)
  const healthScores = healthQuery.isError ? [] : (healthQuery.data ?? [])
  const healthMap = new Map(healthScores.map((h: ClientHealthScore) => [h.client_id, h]))

  const { sortedItems: sortedClients, sortConfig: clientSortConfig, requestSort: requestClientSort } = useTableSort(clients)
  const { selectedIds: selectedClientIds, isSelected: isClientSelected, toggleItem: toggleClient, toggleAll: toggleAllClients, clearSelection: clearClientSelection, selectedCount: selectedClientCount, allSelected: allClientsSelected } = useBulkSelect(clients)

  const bulkClientStatusMutation = useMutation({
    mutationFn: async ({ ids, status }: { ids: number[]; status: string }) => {
      const results = await Promise.allSettled(ids.map((id) => clientsApi.update(id, { status: status as ClientCreate["status"] })))
      const successfulIds = ids.filter((_, index) => results[index].status === "fulfilled")
      const fulfilled = successfulIds.length
      const rejected = results.length - fulfilled
      return { fulfilled, rejected, successfulIds }
    },
    onSuccess: ({ fulfilled, rejected, successfulIds }) => {
      void invalidateClientChange(queryClient, successfulIds)
      clearClientSelection()
      setBulkStatus("")
      if (rejected === 0) {
        toast.success(`${fulfilled} clientes actualizados`)
      } else {
        toast.warning(`${fulfilled} actualizados, ${rejected} fallaron`)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar clientes")),
  })

  function releaseOnboardingAttempt(requestKey = onboardingKey) {
    if (user && requestKey) clearOnboardingKey(user.id, requestKey)
    setOnboardingKeys((keys) => requestKey ? keys.filter((key) => key !== requestKey) : keys)
    setRecoveringOnboarding(Boolean(requestKey && onboardingKeys.some((key) => key !== requestKey)))
  }

  function handleOnboardingResult(result: ClientOnboardingResult, requestKey = onboardingKey) {
    if (result.status === "processing") {
      setRecoveringOnboarding(true)
      return
    }
    if (result.status === "not_committed") {
      releaseOnboardingAttempt(requestKey)
      setOnboardingNotice((notice) => notice ?? "No se confirmó el alta. Revisa los datos y vuelve a intentarlo.")
      return
    }

    releaseOnboardingAttempt(requestKey)
    setOnboardingError(null)
    void invalidateClientChange(queryClient, result.client_id ? [result.client_id] : [])
    closeDialog()
    const created = [
      "Cliente",
      result.contact_ids.length ? `${result.contact_ids.length} contacto${result.contact_ids.length === 1 ? "" : "s"}` : null,
      result.project_id ? "proyecto" : null,
    ].filter(Boolean).join(" + ")
    if (result.undo_state === "undone") {
      toast.message("El alta ya fue deshecha.")
    } else if (result.undo_state === "available") {
      toast.success(result.replayed ? `${created} recuperado. Puedes deshacerlo en Cambios recientes.` : `${created} creado. Puedes deshacerlo en Cambios recientes.`)
    } else {
      toast.success(result.replayed ? `${created} recuperado.` : `${created} creado.`)
    }
  }

  const recoveryQuery = useQuery({
    queryKey: ["client-onboarding", user?.id ?? "anonymous", onboardingKey],
    queryFn: () => clientsApi.recoverOnboarding(onboardingKey!),
    enabled: Boolean(user && canWriteClients && onboardingKey && recoveringOnboarding),
    retry: false,
  })

  useEffect(() => {
    if (recoveryQuery.data) handleOnboardingResult(recoveryQuery.data, onboardingKey)
  // A recovery result is terminal unless it remains processing. Its timestamp keeps a
  // background refetch from reprocessing an old result after the key is cleared.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recoveryQuery.dataUpdatedAt])

  const createMutation = useMutation({
    mutationFn: ({ data, requestKey }: { data: ClientOnboardingCreate; requestKey: string }) => clientsApi.onboard(data, requestKey),
    onSuccess: (result, variables) => handleOnboardingResult(result, variables.requestKey),
    onError: (err) => {
      const code = (err as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail?.code
      if (code === "attempt_cancelled") {
        releaseOnboardingAttempt()
        setOnboardingNotice("Este intento ya se canceló. Revisa los datos antes de crear otro.")
        return
      }
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status && status >= 400 && status < 500) {
        const message = onboardingErrorMessage(err)
        setOnboardingError(message)
        setOnboardingNotice(null)
        setRecoveringOnboarding(true)
        return
      }
      setRecoveringOnboarding(true)
      toast.error("No se pudo confirmar el alta. Estamos comprobando si se guardó antes de permitir otro intento.")
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ClientCreate> }) => clientsApi.update(id, data),
    onSuccess: (_client, { id }) => {
      void invalidateClientChange(queryClient, [id])
      closeDialog()
      toast.success("Cliente actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar cliente")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => clientsApi.delete(id),
    onSuccess: (_result, id) => {
      void invalidateClientChange(queryClient, [id])
      toast.success("Cliente finalizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al finalizar cliente")),
  })

  const hardDeleteMutation = useMutation({
    mutationFn: (id: number) => clientsApi.hardDelete(id),
    onSuccess: (_result, id) => {
      void invalidateClientChange(queryClient, [id])
      toast.success("Cliente eliminado permanentemente")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar cliente")),
  })

  const closeDialog = () => {
    setDialogOpen(false)
    setEditing(null)
    setPrefill(null)
    setIncludeProject(true)
  }

  const openCreate = () => {
    if (!canWriteClients || onboardingKey || storageReadFailed) return
    setEditing(null)
    setPrefill(null)
    setFormKey((k) => k + 1)
    setDialogOpen(true)
  }

  const openEdit = (client: Client) => {
    if (!canWriteClients || onboardingKey || storageReadFailed) return
    setEditing(client)
    setDialogOpen(true)
  }

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const data: ClientCreate = {
      name: fd.get("name") as string,
      email: (fd.get("email") as string) || null,
      phone: (fd.get("phone") as string) || null,
      company: (fd.get("company") as string) || null,
      website: (fd.get("website") as string) || null,
      contract_type: (fd.get("contract_type") as ClientCreate["contract_type"]) || "monthly",
      monthly_budget: fd.get("monthly_budget") ? Number(fd.get("monthly_budget")) : null,
      status: (fd.get("status") as ClientStatus) || "active",
      notes: (fd.get("notes") as string) || null,
      cif: (fd.get("cif") as string) || null,
      vat_number: (fd.get("vat_number") as string) || null,
      is_internal: fd.get("is_internal") === "on",
      is_intermediary_deal: fd.get("is_intermediary_deal") === "on",
      intermediary_name: (fd.get("intermediary_name") as string) || null,
      context: (fd.get("context") as string) || undefined,
      business_model: (fd.get("business_model") as string) || prefill?.business_model || undefined,
    }
    if (editing) {
      updateMutation.mutate({ id: editing.id, data })
    } else {
      const contactName = (fd.get("contact_name") as string) || ""
      const manualContact: ClientContactCreate | undefined = contactName ? {
        name: contactName,
        email: (fd.get("contact_email") as string) || null,
        phone: (fd.get("contact_phone") as string) || null,
        position: (fd.get("contact_position") as string) || null,
        is_primary: true,
      } : undefined
      const selectedExtracted = new Set(
        fd.getAll("extracted_contact").map((value) => Number(value)).filter((value) => Number.isInteger(value) && value >= 0),
      )
      const selectedPrimary = fd.get("extracted_primary")
      const extractedPrimary = typeof selectedPrimary === "string" && /^\d+$/.test(selectedPrimary) ? Number(selectedPrimary) : null
      if (extractedPrimary !== null && (!selectedExtracted.has(extractedPrimary) || !Number.isInteger(extractedPrimary))) {
        toast.error("El contacto principal debe estar incluido en el alta.")
        return
      }
      if (manualContact && extractedPrimary !== null) {
        toast.error("El contacto escrito manualmente ya es principal. Elige sólo uno.")
        return
      }
      const aiContacts = (prefill?.contacts ?? []).flatMap((_contact, index) => {
        if (!selectedExtracted.has(index)) return []
        const name = String(fd.get(`extracted_contact_name_${index}`) ?? "").trim()
        return [{
          name,
          email: String(fd.get(`extracted_contact_email_${index}`) ?? "") || null,
          phone: String(fd.get(`extracted_contact_phone_${index}`) ?? "") || null,
          position: String(fd.get(`extracted_contact_position_${index}`) ?? "") || null,
          company: String(fd.get(`extracted_contact_company_${index}`) ?? "") || null,
          notes: String(fd.get(`extracted_contact_notes_${index}`) ?? "") || null,
          language: String(fd.get(`extracted_contact_language_${index}`) ?? "") || null,
          index,
        }]
      })
      if (aiContacts.some((contact) => !contact.name)) {
        toast.error("Cada contacto incluido necesita un nombre.")
        return
      }
      const contacts: ClientContactCreate[] = [
        ...(manualContact ? [manualContact] : []),
        ...aiContacts.map((contact) => {
          return {
          name: contact.name,
          email: contact.email || null,
          phone: contact.phone || null,
          position: [contact.position, contact.company].filter(Boolean).join(" - ") || null,
          is_primary: !manualContact && contact.index === extractedPrimary,
          notes: contact.notes || null,
          language: contact.language || null,
          }
        }),
      ]
      if (contacts.length > 50) {
        toast.error("El alta admite un máximo de 50 contactos.")
        return
      }
      const projectName = String(fd.get("project_name") ?? "").trim()
      const project: ClientOnboardingProjectCreate | null = includeProject && projectName ? {
        name: projectName,
        description: String(fd.get("project_description") ?? "") || null,
        project_type: String(fd.get("project_type") ?? "") || null,
        is_recurring: fd.get("project_is_recurring") === "on",
        pricing_model: String(fd.get("project_pricing_model") ?? "") || null,
        unit_price: fd.get("project_unit_price") ? Number(fd.get("project_unit_price")) : null,
        unit_label: String(fd.get("project_unit_label") ?? "") || null,
        scope: String(fd.get("project_scope") ?? "") || null,
        monthly_fee: fd.get("project_monthly_fee") ? Number(fd.get("project_monthly_fee")) : null,
        budget_amount: fd.get("project_budget_amount") ? Number(fd.get("project_budget_amount")) : null,
        start_date: String(fd.get("project_start_date") ?? "") || null,
        target_end_date: String(fd.get("project_target_end_date") ?? "") || null,
      } : null
      if (includeProject && prefill?.project?.name && !projectName) {
        toast.error("El proyecto incluido necesita un nombre.")
        return
      }
      if (project && !canWriteProjects) {
        toast.error("No tienes permiso para crear el proyecto incluido en este alta.")
        return
      }
      if (!user || !canWriteClients) return
      if (storageReadFailed) {
        toast.error("Este navegador no pudo comprobar si hay un alta pendiente. Habilita el almacenamiento local antes de crear un cliente.")
        return
      }
      const requestKey = onboardingKey ?? newRequestKey()
      if (!onboardingKey && !persistOnboardingKey(user.id, requestKey)) {
        toast.error("Este navegador no pudo preparar una recuperación segura. Habilita el almacenamiento local antes de crear el cliente.")
        return
      }
      if (!onboardingKey) setOnboardingKeys((keys) => [...keys, requestKey])
      setRecoveringOnboarding(false)
      setOnboardingNotice(null)
      setOnboardingError(null)
      createMutation.mutate({ data: { client: data, contacts, project }, requestKey })
    }
  }

  return (
    <div className="space-y-4" onClick={() => openMenuId !== null && setOpenMenuId(null)}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Clientes</h2>
          {data && <p className="text-sm text-muted-foreground mt-1">
            {STATUS_TABS.find((item) => item.value === tab)?.label} · {COHORTS.find((item) => item.value === cohort)?.label} · {data.total} resultados
          </p>}
        </div>
        <Button onClick={openCreate} disabled={!canWriteClients || !!onboardingKey || storageReadFailed}>
          <Plus className="h-4 w-4 mr-2" /> Nuevo cliente
        </Button>
      </div>

      {(onboardingKey || onboardingNotice || storageReadFailed) && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm">
          <span>
            {onboardingNotice ?? (storageReadFailed
              ? "Este navegador no pudo comprobar si hay un alta pendiente. Habilita el almacenamiento local antes de crear o editar clientes."
              : recoveryQuery.isError
              ? "No se pudo comprobar el alta anterior. No crees ni edites clientes hasta resolverla."
              : recoveryQuery.data?.status === "processing"
                ? "El alta anterior sigue procesándose. Espera antes de crear o editar clientes."
                : "Estamos comprobando un alta anterior antes de permitir cambios.")}
          </span>
          {onboardingKey && <Button variant="outline" size="sm" disabled={recoveryQuery.isFetching} onClick={() => void recoveryQuery.refetch()}>
            {recoveryQuery.isFetching ? "Comprobando…" : "Comprobar alta"}
          </Button>}
        </div>
      )}

      {/* Tabs */}
      <div className="flex flex-wrap gap-2">
        {STATUS_TABS.map((t) => (
          <Button
            key={t.value}
            variant={tab === t.value ? "default" : "outline"}
            size="sm"
            onClick={() => { setTab(t.value); reset() }}
          >
            {t.label}
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2" aria-label="Población de clientes">
        <span className="text-xs font-medium text-muted-foreground">Tipo de cliente</span>
        {COHORTS.map((item) => (
          <Button
            key={item.value}
            variant={cohort === item.value ? "secondary" : "ghost"}
            size="sm"
            onClick={() => { setCohort(item.value); reset(); clearClientSelection() }}
          >
            {item.label}
          </Button>
        ))}
      </div>

      {healthQuery.isError && !healthDenied && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm text-muted-foreground">
          <span>No se pudo actualizar la salud de clientes.</span>
          <Button variant="outline" size="sm" onClick={() => void healthQuery.refetch()}>Reintentar salud</Button>
        </div>
      )}
      {healthDenied && !clientsDenied && <p role="alert" className="text-sm text-muted-foreground">No tienes acceso a la salud de clientes.</p>}

      {/* Table */}
      {isLoading ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>Nombre</TableHead>
              <TableHead>Empresa</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Contrato</TableHead>
              {isAdmin && <TableHead>Presupuesto</TableHead>}
              <TableHead>Estado</TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Salud
                  <InfoTooltip
                    content={
                      <div className="space-y-1.5">
                        <p className="font-semibold">Condiciones observables</p>
                        <p className="text-muted-foreground">Muestra riesgos comprobados en comunicación, tareas, resúmenes, rentabilidad y seguimientos. Si falta una fuente, se indica como información incompleta.</p>
                      </div>
                    }
                  />
                </span>
              </TableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 5 }).map((_, i) => <SkeletonTableRow key={i} cols={isAdmin ? 9 : 8} />)}
          </TableBody>
        </Table>
      ) : clientsDenied ? (
        <div role="alert" className="py-12 text-center">
          <p className="font-medium">No tienes acceso a la lista de clientes.</p>
          <Button variant="outline" className="mt-3" onClick={() => void clientsQuery.refetch()}>Reintentar</Button>
        </div>
      ) : clientsQuery.isError && !data ? (
        <div role="alert" className="py-12 text-center">
          <p className="font-medium">No se pudieron cargar los clientes. Reintenta en unos momentos.</p>
          <Button variant="outline" className="mt-3" onClick={() => void clientsQuery.refetch()}>Reintentar</Button>
        </div>
      ) : (
        <>
        {/* Mobile card list */}
        <div className="sm:hidden space-y-3">
          {sortedClients.map((c) => {
            const h = healthMap.get(c.id)
            const presentation = h ? clientHealthPresentation(h) : null
            return (
              <div key={c.id} className="border border-border rounded-xl p-4 bg-card space-y-2">
                <div className="flex items-start justify-between">
                  <div>
                    <Link to={`/clients/${c.id}`} className="font-medium text-brand hover:underline">
                      {c.name || "Sin nombre"}
                    </Link>
                    {c.company && <p className="text-sm text-muted-foreground">{c.company}</p>}
                  </div>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" aria-label="Editar cliente" disabled={!canWriteClients || !!onboardingKey || storageReadFailed} onClick={() => openEdit(c)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {statusBadge(c.status)}
                  {isAdmin && c.monthly_budget != null && <Badge variant="outline" className="text-xs">{formatCurrency(c.monthly_budget)}</Badge>}
                  {c.status !== "active" ? <span className="text-xs text-muted-foreground">No evaluado · solo activos</span>
                    : presentation ? <Badge variant={presentation.variant}>{presentation.label}</Badge>
                    : healthQuery.isLoading ? <span className="text-xs text-muted-foreground">Consultando…</span>
                    : <span className="text-xs text-muted-foreground">Información no disponible</span>}
                </div>
              </div>
            )
          })}
          {clients.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">No hay clientes {tab === "all" ? "" : STATUS_TABS.find((item) => item.value === tab)?.label.toLowerCase()} {cohort === "all" ? "" : COHORTS.find((item) => item.value === cohort)?.label.toLowerCase()}</div>
          )}
        </div>

        {/* Desktop table */}
        <Table className="hidden sm:table">
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <input
                  type="checkbox"
                  aria-label="Seleccionar todos los clientes visibles"
                  checked={allClientsSelected}
                  onChange={toggleAllClients}
                  className="rounded border-border"
                />
              </TableHead>
              <SortableTableHead sortKey="name" currentSort={clientSortConfig} onSort={requestClientSort}>Nombre</SortableTableHead>
              <TableHead>Empresa</TableHead>
              <TableHead className="hidden md:table-cell">Email</TableHead>
              <TableHead>Contrato</TableHead>
              {isAdmin && <SortableTableHead sortKey="monthly_budget" currentSort={clientSortConfig} onSort={requestClientSort}>Presupuesto</SortableTableHead>}
              <TableHead>Estado</TableHead>
              <TableHead className="hidden md:table-cell">
                <span className="inline-flex items-center gap-1">
                  Salud
                  <InfoTooltip
                    content={
                      <div className="space-y-1.5">
                        <p className="font-semibold">Condiciones observables</p>
                        <p className="text-muted-foreground">Los riesgos comprobados tienen prioridad. Las fuentes que faltan se muestran como información incompleta.</p>
                      </div>
                    }
                  />
                </span>
              </TableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedClients.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <input
                    type="checkbox"
                    aria-label={`Seleccionar cliente ${c.name || 'Sin nombre'}`}
                    checked={isClientSelected(c.id)}
                    onChange={() => toggleClient(c.id)}
                    className="rounded border-border"
                  />
                </TableCell>
                <TableCell className="font-medium">
                  <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                      <Link to={`/clients/${c.id}`} className="break-words text-brand hover:underline">
                        {c.name || 'Sin nombre'}
                      </Link>
                      {c.is_internal && (
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5 border-purple-500/50 text-purple-400">
                          Interno
                        </Badge>
                      )}
                      {c.engine_project_id && engineConfig?.engine_frontend_url && (
                        <a
                          href={`${engineConfig.engine_frontend_url}/p/${c.engine_project_id}/dashboard`}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Abrir en Engine"
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-0.5"
                        >
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5 gap-0.5">
                            <ExternalLink className="h-3 w-3" />
                            Engine
                          </Badge>
                        </a>
                      )}
                    </div>
                    {c.is_intermediary_deal && (
                      <p className="mt-1 break-words text-xs font-normal text-muted-foreground" title={c.intermediary_name ? `Vía ${c.intermediary_name}` : "Agencia intermediaria"}>
                        {c.intermediary_name ? `Vía ${c.intermediary_name}` : "Agencia intermediaria"}
                      </p>
                    )}
                  </div>
                </TableCell>
                <TableCell>{c.company || "-"}</TableCell>
                <TableCell className="hidden md:table-cell">{c.email || "-"}</TableCell>
                <TableCell>{c.contract_type === "monthly" ? "Mensual" : "Puntual"}</TableCell>
                {isAdmin && <TableCell className="mono">{c.monthly_budget != null ? formatCurrency(c.monthly_budget) : "-"}</TableCell>}
                <TableCell>{statusBadge(c.status)}</TableCell>
                <TableCell className="hidden md:table-cell">
                  {(() => {
                    if (c.status !== "active") return <span className="text-muted-foreground text-xs">No evaluado · solo activos</span>
                    const h = healthMap.get(c.id)
                    if (!h) return <span className="text-muted-foreground text-xs">{healthQuery.isLoading ? "Consultando…" : "Información no disponible"}</span>
                    const presentation = clientHealthPresentation(h)
                    return (
                      <Badge variant={presentation.variant} title={(Object.values(h.observations)).join(" · ")}>{presentation.label}</Badge>
                    )
                  })()}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" aria-label="Editar cliente" disabled={!canWriteClients || !!onboardingKey || storageReadFailed} onClick={() => openEdit(c)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <div className="relative">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Más opciones"
                        onClick={() => setOpenMenuId(openMenuId === c.id ? null : c.id)}
                      >
                        <MoreVertical className="h-4 w-4" />
                      </Button>
                      {openMenuId === c.id && (
                        <div className="absolute right-0 top-full z-50 mt-1 w-52 rounded-md border bg-background shadow-md">
                          <button
                            className="flex w-full items-center px-3 py-2 text-left text-sm hover:bg-accent"
                            onClick={() => { setDeleteId(c.id); setOpenMenuId(null) }}
                          >
                            Finalizar
                          </button>
                          {isAdmin && (
                            <button
                              className="flex w-full items-center px-3 py-2 text-left text-sm text-destructive hover:bg-accent"
                              onClick={() => { setHardDeleteId(c.id); setOpenMenuId(null) }}
                            >
                              Borrar permanentemente
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {clients.length === 0 && (
              <EmptyTableState colSpan={9} icon={Users} title="Sin resultados" description={`No hay clientes ${tab === "all" ? "" : STATUS_TABS.find((item) => item.value === tab)?.label.toLowerCase()} ${cohort === "all" ? "" : COHORTS.find((item) => item.value === cohort)?.label.toLowerCase()}.`} />
            )}
          </TableBody>
        </Table>
        </>
      )}

      <Pagination page={page} pageSize={pageSize} total={data?.total ?? 0} onPageChange={setPage} />

      {/* Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar cliente" : "Nuevo cliente"}</DialogTitle>
        </DialogHeader>
        {!editing && !onboardingKey && !storageReadFailed && <AiFillSection onExtracted={(data) => { setPrefill(data); setIncludeProject(true); setFormKey((k) => k + 1) }} />}
        <form key={formKey} onSubmit={handleSubmit} className="space-y-4">
          {!editing && (onboardingKey || onboardingNotice || onboardingError || storageReadFailed) && (
            <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm">
              <span>{onboardingError ?? onboardingNotice ?? (storageReadFailed
                ? "Este navegador no pudo comprobar si hay un alta pendiente."
                : recoveryQuery.isError
                  ? "No se pudo comprobar el alta anterior."
                  : "Estamos comprobando el alta anterior antes de permitir cambios.")}</span>
              {onboardingKey && <Button type="button" variant="outline" size="sm" disabled={recoveryQuery.isFetching} onClick={() => void recoveryQuery.refetch()}>
                {recoveryQuery.isFetching ? "Comprobando…" : "Comprobar alta"}
              </Button>}
            </div>
          )}
          <fieldset disabled={!!onboardingKey || storageReadFailed || createMutation.isPending || (editing !== null && updateMutation.isPending)} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="name">Nombre *</Label>
              <Input id="name" name="name" defaultValue={prefill?.name ?? editing?.name ?? ""} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="company">Empresa</Label>
              <Input id="company" name="company" defaultValue={prefill?.company ?? editing?.company ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" name="email" type="email" defaultValue={prefill?.email ?? editing?.email ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">Teléfono</Label>
              <Input id="phone" name="phone" defaultValue={prefill?.phone ?? editing?.phone ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="website">Web</Label>
              <Input id="website" name="website" defaultValue={prefill?.website ?? editing?.website ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cif">CIF</Label>
              <Input id="cif" name="cif" defaultValue={editing?.cif ?? ""} placeholder="B12345678" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="vat_number">VAT Number</Label>
              <Input id="vat_number" name="vat_number" defaultValue={editing?.vat_number ?? ""} placeholder="ESB12345678" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="contract_type">Tipo de contrato</Label>
              <Select id="contract_type" name="contract_type" defaultValue={prefill?.contract_type ?? editing?.contract_type ?? "monthly"}>
                <option value="monthly">Mensual</option>
                <option value="one_time">Puntual</option>
              </Select>
            </div>
            {isAdmin && editing?.monthly_budget != null && (
              <div className="space-y-2">
                <Label htmlFor="monthly_budget">Presupuesto mensual (EUR) <span className="text-xs text-muted-foreground">(derivado de proyectos)</span></Label>
                <Input
                  id="monthly_budget"
                  name="monthly_budget"
                  type="number"
                  step="0.01"
                  defaultValue={editing.monthly_budget ?? ""}
                  className="opacity-60"
                  title="Este campo se deriva de los proyectos activos del cliente"
                />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="status">Estado</Label>
              <Select id="status" name="status" defaultValue={editing?.status ?? "active"}>
                <option value="active">Activo</option>
                <option value="paused">Pausado</option>
                <option value="finished">Finalizado</option>
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="notes">Notas</Label>
            <Textarea id="notes" name="notes" defaultValue={prefill?.notes ?? editing?.notes ?? ""} />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_internal"
              name="is_internal"
              defaultChecked={editing?.is_internal ?? false}
              className="rounded border-border"
            />
            <Label htmlFor="is_internal" className="cursor-pointer text-sm font-normal">
              Cliente interno (Magnify)
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_intermediary_deal"
              name="is_intermediary_deal"
              defaultChecked={prefill?.is_intermediary_deal ?? editing?.is_intermediary_deal ?? false}
              className="rounded border-border"
            />
            <Label htmlFor="is_intermediary_deal" className="cursor-pointer text-sm font-normal">
              Hay agencia intermediaria
            </Label>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="intermediary_name">Agencia intermediaria</Label>
            <Input id="intermediary_name" name="intermediary_name" defaultValue={prefill?.intermediary_name ?? editing?.intermediary_name ?? ""} placeholder="Peak Ace, etc." />
          </div>
          {/* Contacto principal (solo al crear) */}
          {!editing && (() => {
            const extractedContacts = prefill?.contacts ?? []
            const declaredPrimary = extractedContacts.filter((contact) => contact.is_primary)
            const hasAmbiguousPrimary = declaredPrimary.length > 1
            return (
              <div className="space-y-3 border border-border rounded-lg p-3">
                <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Contacto principal</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="contact_name" className="text-xs">Nombre</Label>
                    <Input id="contact_name" name="contact_name" placeholder="Nombre del contacto" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="contact_email" className="text-xs">Email</Label>
                    <Input id="contact_email" name="contact_email" type="email" placeholder="contacto@empresa.com" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="contact_phone" className="text-xs">Teléfono</Label>
                    <Input id="contact_phone" name="contact_phone" placeholder="+34 600 000 000" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="contact_position" className="text-xs">Cargo</Label>
                    <Input id="contact_position" name="contact_position" placeholder="CEO, Marketing Director..." />
                  </div>
                </div>
                {extractedContacts.length > 0 && (
                  <div className="space-y-2 rounded-md bg-muted/30 p-3 text-sm">
                    <p className="font-medium">Contactos detectados</p>
                    <p className="text-xs text-muted-foreground">Elige cuáles crear y, si corresponde, cuál es el principal. Puedes dejar contactos fuera.</p>
                    {hasAmbiguousPrimary && <p role="alert" className="text-xs">La extracción marcó más de un contacto principal. Elige sólo uno antes de crear.</p>}
                    {extractedContacts.map((contact, index) => (
                      <div key={`${contact.name}-${index}`} className="space-y-2 rounded border p-2 text-xs">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          <label className="flex items-center gap-1.5"><input type="checkbox" name="extracted_contact" value={index} defaultChecked className="rounded border-border" />Crear contacto</label>
                          <label className="flex items-center gap-1.5"><input type="radio" name="extracted_primary" value={index} defaultChecked={!hasAmbiguousPrimary && contact.is_primary === true} />Principal</label>
                        </div>
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          <div><Label htmlFor={`extracted_contact_name_${index}`} className="text-xs">Nombre</Label><Input id={`extracted_contact_name_${index}`} name={`extracted_contact_name_${index}`} defaultValue={contact.name} /></div>
                          <div><Label htmlFor={`extracted_contact_email_${index}`} className="text-xs">Email</Label><Input id={`extracted_contact_email_${index}`} name={`extracted_contact_email_${index}`} defaultValue={contact.email ?? ""} /></div>
                          <div><Label htmlFor={`extracted_contact_phone_${index}`} className="text-xs">Teléfono</Label><Input id={`extracted_contact_phone_${index}`} name={`extracted_contact_phone_${index}`} defaultValue={contact.phone ?? ""} /></div>
                          <div><Label htmlFor={`extracted_contact_position_${index}`} className="text-xs">Cargo</Label><Input id={`extracted_contact_position_${index}`} name={`extracted_contact_position_${index}`} defaultValue={contact.position ?? ""} /></div>
                        </div>
                        <details><summary className="cursor-pointer text-muted-foreground">Más campos</summary><div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2"><div><Label htmlFor={`extracted_contact_company_${index}`} className="text-xs">Empresa</Label><Input id={`extracted_contact_company_${index}`} name={`extracted_contact_company_${index}`} defaultValue={contact.company ?? ""} /></div><div><Label htmlFor={`extracted_contact_language_${index}`} className="text-xs">Idioma</Label><Input id={`extracted_contact_language_${index}`} name={`extracted_contact_language_${index}`} defaultValue={contact.language ?? ""} /></div><div className="sm:col-span-2"><Label htmlFor={`extracted_contact_notes_${index}`} className="text-xs">Notas</Label><Textarea id={`extracted_contact_notes_${index}`} name={`extracted_contact_notes_${index}`} defaultValue={contact.notes ?? ""} /></div></div></details>
                      </div>
                    ))}
                    <label className="flex items-center gap-1.5 text-xs">
                      <input type="radio" name="extracted_primary" value="" />
                      Ninguno de los contactos detectados
                    </label>
                  </div>
                )}
              </div>
            )
          })()}
          {prefill?.context && (
            <div className="space-y-2">
              <Label htmlFor="context">Contexto (generado por IA)</Label>
              <Textarea id="context" name="context" defaultValue={prefill.context} className="min-h-[80px]" />
            </div>
          )}
          {prefill?.project?.name && (
            <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
              <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" name="create_project" checked={includeProject} onChange={(event) => setIncludeProject(event.target.checked)} className="rounded border-border" />Crear proyecto detectado</label>
              <fieldset disabled={!includeProject} className="space-y-3"><div><Label htmlFor="project_name">Nombre del proyecto</Label><Input id="project_name" name="project_name" defaultValue={prefill.project.name} /></div>
              <div><Label htmlFor="project_description">Descripción</Label><Textarea id="project_description" name="project_description" defaultValue={prefill.project.description ?? ""} /></div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2"><div><Label htmlFor="project_start_date">Inicio</Label><Input id="project_start_date" name="project_start_date" type="date" defaultValue={prefill.project.start_date ?? ""} /></div><div><Label htmlFor="project_target_end_date">Fecha objetivo</Label><Input id="project_target_end_date" name="project_target_end_date" type="date" defaultValue={prefill.project.target_end_date ?? ""} /></div></div>
              <details><summary className="cursor-pointer text-sm text-muted-foreground">Campos avanzados</summary><div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2"><div><Label htmlFor="project_type">Tipo</Label><Input id="project_type" name="project_type" defaultValue={prefill.project.project_type ?? ""} /></div><div><Label htmlFor="project_pricing_model">Modelo de precio</Label><Input id="project_pricing_model" name="project_pricing_model" defaultValue={prefill.project.pricing_model ?? ""} /></div><div><Label htmlFor="project_monthly_fee">Cuota mensual</Label><Input id="project_monthly_fee" name="project_monthly_fee" type="number" step="0.01" defaultValue={prefill.project.monthly_fee ?? ""} /></div><div><Label htmlFor="project_budget_amount">Presupuesto</Label><Input id="project_budget_amount" name="project_budget_amount" type="number" step="0.01" defaultValue={prefill.project.budget_amount ?? ""} /></div><div><Label htmlFor="project_unit_price">Precio unitario</Label><Input id="project_unit_price" name="project_unit_price" type="number" step="0.01" defaultValue={prefill.project.unit_price ?? ""} /></div><div><Label htmlFor="project_unit_label">Unidad</Label><Input id="project_unit_label" name="project_unit_label" defaultValue={prefill.project.unit_label ?? ""} /></div><div className="sm:col-span-2"><Label htmlFor="project_scope">Alcance</Label><Textarea id="project_scope" name="project_scope" defaultValue={prefill.project.scope ?? ""} /></div><label className="flex items-center gap-2 text-sm"><input type="checkbox" name="project_is_recurring" defaultChecked={prefill.project.is_recurring ?? false} />Recurrente</label></div></details></fieldset>
            </div>
          )}
          </fieldset>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={closeDialog}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!canWriteClients || !!onboardingKey || storageReadFailed || createMutation.isPending || updateMutation.isPending}>
              {editing ? "Guardar" : createMutation.isPending ? "Creando…" : "Crear"}
            </Button>
          </div>
        </form>
      </Dialog>

      {/* Finalizar Confirm */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Finalizar cliente"
        description="El cliente se marcará como finalizado. Sus tareas y datos no se eliminarán."
        confirmLabel="Finalizar"
        onConfirm={() => {
          if (deleteId !== null) {
            deleteMutation.mutate(deleteId)
            setDeleteId(null)
          }
        }}
      />

      {/* Hard Delete Confirm */}
      <ConfirmDialog
        open={hardDeleteId !== null}
        onOpenChange={(open) => !open && setHardDeleteId(null)}
        title="Borrar cliente permanentemente"
        description="Se eliminarán el cliente y TODOS sus datos (proyectos, tareas, contactos, comunicaciones...). Esta acción no se puede deshacer."
        confirmLabel="Borrar permanentemente"
        onConfirm={() => {
          if (hardDeleteId !== null) {
            hardDeleteMutation.mutate(hardDeleteId)
            setHardDeleteId(null)
          }
        }}
      />

      {/* Bulk Actions */}
      <BulkActionBar selectedCount={selectedClientCount} onClear={clearClientSelection}>
        <Select value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)} className="h-8 text-xs w-36">
          <option value="">Cambiar estado…</option>
          <option value="active">Activo</option>
          <option value="paused">Pausado</option>
          <option value="finished">Finalizado</option>
        </Select>
        <Button
          size="sm"
          disabled={!bulkStatus || bulkClientStatusMutation.isPending}
          onClick={() => bulkClientStatusMutation.mutate({ ids: Array.from(selectedClientIds), status: bulkStatus })}
        >
          {bulkClientStatusMutation.isPending && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
          Aplicar
        </Button>
      </BulkActionBar>
    </div>
  )
}

function AiFillSection({ onExtracted }: { onExtracted: (data: ClientExtract) => void }) {
  const [mode, setMode] = useState<"closed" | "paste" | "file">("closed")
  const [pasteText, setPasteText] = useState("")
  const [file, setFile] = useState<File | null>(null)

  const extractMutation = useMutation({
    mutationFn: () => clientsApi.extractContext({
      file: mode === "file" ? file ?? undefined : undefined,
      rawText: mode === "paste" ? pasteText : undefined,
    }),
    onSuccess: (data) => {
      onExtracted(data)
      toast.success("Datos extraídos — revisa y ajusta antes de crear")
      setMode("closed")
      setPasteText("")
      setFile(null)
    },
    onError: (err: unknown) => toast.error(getErrorMessage(err, "Error al extraer datos")),
  })

  if (mode === "closed") {
    return (
      <div className="flex gap-2 mb-4">
        <Button type="button" variant="outline" size="sm" onClick={() => setMode("paste")}>
          <Sparkles className="h-3.5 w-3.5 mr-1.5" />
          Pegar contexto
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => setMode("file")}>
          <Upload className="h-3.5 w-3.5 mr-1.5" />
          Subir TXT/MD
        </Button>
      </div>
    )
  }

  return (
    <div className="mb-4 p-3 rounded-lg border border-dashed border-brand/40 bg-brand/5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-brand" />
          {mode === "paste" ? "Pega la información del cliente" : "Sube un archivo .txt o .md"}
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={() => { setMode("closed"); setPasteText(""); setFile(null) }}>
          Cancelar
        </Button>
      </div>
      {mode === "paste" ? (
        <textarea
          className="w-full min-h-[120px] text-sm bg-background border border-input rounded-md p-3 resize-y focus:outline-none focus:ring-2 focus:ring-ring"
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder="Pega aquí emails, notas, resúmenes de reunión, briefings... Claude extraerá los datos del cliente automáticamente."
        />
      ) : (
        <Input
          type="file"
          accept=".txt,.md"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      )}
      <Button
        type="button"
        size="sm"
        onClick={() => extractMutation.mutate()}
        disabled={extractMutation.isPending || (mode === "paste" ? !pasteText.trim() : !file)}
      >
        {extractMutation.isPending ? (
          <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Analizando...</>
        ) : (
          <><Sparkles className="h-3.5 w-3.5 mr-1.5" /> Extraer datos con IA</>
        )}
      </Button>
    </div>
  )
}
