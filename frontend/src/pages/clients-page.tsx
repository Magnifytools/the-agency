import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { clientsApi, clientHealthApi, engineApi } from "@/lib/api"
import type { Client, ClientCreate, ClientStatus, ClientHealthScore } from "@/lib/types"
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
import { Plus, Pencil, MoreVertical, Users, Heart, Loader2, ExternalLink } from "lucide-react"
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

const STATUS_TABS: { label: string; value: ClientStatus | "all" }[] = [
  { label: "Todos", value: "all" },
  { label: "Activos", value: "active" },
  { label: "Pausados", value: "paused" },
  { label: "Finalizados", value: "finished" },
]

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
  const queryClient = useQueryClient()
  const { isAdmin } = useAuth()
  const { page, pageSize, setPage, reset } = usePagination(25)
  const [tab, setTab] = useState<ClientStatus | "all">("all")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Client | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [hardDeleteId, setHardDeleteId] = useState<number | null>(null)
  const [openMenuId, setOpenMenuId] = useState<number | null>(null)
  const [bulkStatus, setBulkStatus] = useState("")

  const { data: engineConfig } = useQuery({
    queryKey: ["engine-config"],
    queryFn: () => engineApi.getConfig(),
    staleTime: 10 * 60_000,
  })

  const { data, isLoading } = useQuery({
    queryKey: ["clients", tab, page, pageSize],
    queryFn: () => clientsApi.list({ status: tab === "all" ? undefined : tab, page, page_size: pageSize }),
  })
  const clients = data?.items ?? []

  const { data: healthScores = [] } = useQuery({
    queryKey: ["client-health-scores"],
    queryFn: () => clientHealthApi.list(),
    staleTime: 60_000,
  })
  const healthMap = new Map(healthScores.map((h: ClientHealthScore) => [h.client_id, h]))

  const { sortedItems: sortedClients, sortConfig: clientSortConfig, requestSort: requestClientSort } = useTableSort(clients)
  const { selectedIds: selectedClientIds, isSelected: isClientSelected, toggleItem: toggleClient, toggleAll: toggleAllClients, clearSelection: clearClientSelection, selectedCount: selectedClientCount, allSelected: allClientsSelected } = useBulkSelect(clients)

  const bulkClientStatusMutation = useMutation({
    mutationFn: async ({ ids, status }: { ids: number[]; status: string }) => {
      const results = await Promise.allSettled(ids.map((id) => clientsApi.update(id, { status: status as ClientCreate["status"] })))
      const fulfilled = results.filter((r) => r.status === "fulfilled").length
      const rejected = results.length - fulfilled
      return { fulfilled, rejected }
    },
    onSuccess: ({ fulfilled, rejected }) => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
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

  const createMutation = useMutation({
    mutationFn: (data: ClientCreate) => clientsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
      closeDialog()
      toast.success("Cliente creado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear cliente")),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ClientCreate> }) => clientsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
      closeDialog()
      toast.success("Cliente actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar cliente")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => clientsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
      toast.success("Cliente finalizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al finalizar cliente")),
  })

  const hardDeleteMutation = useMutation({
    mutationFn: (id: number) => clientsApi.hardDelete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
      toast.success("Cliente eliminado permanentemente")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar cliente")),
  })

  const closeDialog = () => {
    setDialogOpen(false)
    setEditing(null)
  }

  const openCreate = () => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (client: Client) => {
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
    }
    if (editing) {
      updateMutation.mutate({ id: editing.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  return (
    <div className="space-y-4" onClick={() => openMenuId !== null && setOpenMenuId(null)}>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Clientes</h2>
          {data && <p className="text-sm text-muted-foreground mt-1">{data.total} clientes · {clients.length} en vista</p>}
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" /> Nuevo cliente
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
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
                        <p className="font-semibold">Puntuación de salud del cliente (0–100)</p>
                        <p className="text-muted-foreground">Combina 5 factores: comunicación reciente, tareas completadas, digests enviados, rentabilidad y followups pendientes.</p>
                        <div className="flex flex-col gap-0.5 pt-0.5">
                          <span className="text-green-600 font-medium">● ≥ 70 — Saludable</span>
                          <span className="text-amber-500 font-medium">● 40–69 — Atención</span>
                          <span className="text-red-500 font-medium">● &lt; 40 — En riesgo</span>
                        </div>
                        <p className="text-muted-foreground text-[11px] pt-0.5">Pasa el ratón sobre la puntuación para ver el desglose.</p>
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
      ) : (
        <>
        {/* Mobile card list */}
        <div className="sm:hidden space-y-3">
          {sortedClients.map((c) => {
            const h = healthMap.get(c.id)
            const healthColor = h ? (h.risk_level === "healthy" ? "text-green-600" : h.risk_level === "warning" ? "text-amber-500" : "text-red-500") : ""
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
                    <Button variant="ghost" size="icon" aria-label="Editar cliente" onClick={() => openEdit(c)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {statusBadge(c.status)}
                  {isAdmin && c.monthly_budget != null && <Badge variant="outline" className="text-xs">{c.monthly_budget}€</Badge>}
                  {h && <span className={`inline-flex items-center gap-1 text-xs font-semibold ${healthColor}`}><Heart className="h-3 w-3" />{h.score}</span>}
                </div>
              </div>
            )
          })}
          {clients.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">Sin clientes todavía</div>
          )}
        </div>

        {/* Desktop table */}
        <Table className="hidden sm:table">
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <input
                  type="checkbox"
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
                        <p className="font-semibold">Puntuación de salud del cliente (0–100)</p>
                        <p className="text-muted-foreground">Combina 5 factores: comunicación reciente, tareas completadas, digests enviados, rentabilidad y followups pendientes.</p>
                        <div className="flex flex-col gap-0.5 pt-0.5">
                          <span className="text-green-600 font-medium">● ≥ 70 — Saludable</span>
                          <span className="text-amber-500 font-medium">● 40–69 — Atención</span>
                          <span className="text-red-500 font-medium">● &lt; 40 — En riesgo</span>
                        </div>
                        <p className="text-muted-foreground text-[11px] pt-0.5">Pasa el ratón sobre la puntuación para ver el desglose.</p>
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
                    checked={isClientSelected(c.id)}
                    onChange={() => toggleClient(c.id)}
                    className="rounded border-border"
                  />
                </TableCell>
                <TableCell className="font-medium">
                  <span className="flex items-center gap-1.5">
                    <Link to={`/clients/${c.id}`} className="hover:underline text-brand">
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
                  </span>
                </TableCell>
                <TableCell>{c.company || "-"}</TableCell>
                <TableCell className="hidden md:table-cell">{c.email || "-"}</TableCell>
                <TableCell>{c.contract_type === "monthly" ? "Mensual" : "Puntual"}</TableCell>
                {isAdmin && <TableCell className="mono">{c.monthly_budget != null ? `${c.monthly_budget}€` : "-"}</TableCell>}
                <TableCell>{statusBadge(c.status)}</TableCell>
                <TableCell className="hidden md:table-cell">
                  {(() => {
                    const h = healthMap.get(c.id)
                    if (!h) return <span className="text-muted-foreground text-xs">-</span>
                    const color = h.risk_level === "healthy" ? "text-green-600" : h.risk_level === "warning" ? "text-amber-500" : "text-red-500"
                    return (
                      <span className={`inline-flex items-center gap-1 text-xs font-semibold ${color}`} title={`Comunicacion: ${h.factors.communication} | Tareas: ${h.factors.tasks} | Digests: ${h.factors.digests} | Rentabilidad: ${h.factors.profitability} | Followups: ${h.factors.followups}`}>
                        <Heart className="h-3 w-3" />{h.score}
                      </span>
                    )
                  })()}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" aria-label="Editar cliente" onClick={() => openEdit(c)}>
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
              <EmptyTableState colSpan={9} icon={Users} title="Sin clientes todavía" description="Aquí verás tus clientes con estado, presupuesto y contacto." />
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
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="name">Nombre *</Label>
              <Input id="name" name="name" defaultValue={editing?.name ?? ""} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="company">Empresa</Label>
              <Input id="company" name="company" defaultValue={editing?.company ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" name="email" type="email" defaultValue={editing?.email ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">Teléfono</Label>
              <Input id="phone" name="phone" defaultValue={editing?.phone ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="website">Web</Label>
              <Input id="website" name="website" defaultValue={editing?.website ?? ""} />
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
              <Select id="contract_type" name="contract_type" defaultValue={editing?.contract_type ?? "monthly"}>
                <option value="monthly">Mensual</option>
                <option value="one_time">Puntual</option>
              </Select>
            </div>
            {isAdmin && (
              <div className="space-y-2">
                <Label htmlFor="monthly_budget">Presupuesto mensual (€)</Label>
                <Input
                  id="monthly_budget"
                  name="monthly_budget"
                  type="number"
                  step="0.01"
                  defaultValue={editing?.monthly_budget ?? ""}
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
            <Textarea id="notes" name="notes" defaultValue={editing?.notes ?? ""} />
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
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={closeDialog}>
              Cancelar
            </Button>
            <Button type="submit">{editing ? "Guardar" : "Crear"}</Button>
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
