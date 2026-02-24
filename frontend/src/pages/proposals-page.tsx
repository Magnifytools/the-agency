import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { format } from "date-fns"
import { FileText, Plus, Trash2, Download } from "lucide-react"
import { proposalsApi, clientsApi } from "@/lib/api"
import type { Proposal, ProposalCreate, ProposalUpdate, ProposalStatus } from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

const statusConfig: Record<ProposalStatus, { label: string; variant: "default" | "secondary" | "success" | "destructive" }> = {
    draft: { label: "Borrador", variant: "secondary" },
    sent: { label: "Enviada", variant: "default" },
    accepted: { label: "Aceptada", variant: "success" },
    rejected: { label: "Rechazada", variant: "destructive" },
}

export default function ProposalsPage() {
    const queryClient = useQueryClient()
    const [dialogOpen, setDialogOpen] = useState(false)
    const [editing, setEditing] = useState<Proposal | null>(null)
    const [deleteId, setDeleteId] = useState<number | null>(null)

    // Form State
    const [title, setTitle] = useState("")
    const [clientId, setClientId] = useState<number | "">("")
    const [status, setStatus] = useState<ProposalStatus>("draft")
    const [budget, setBudget] = useState<string>("")
    const [scope, setScope] = useState("")
    const [validDays, setValidDays] = useState("30")

    const { data: proposals = [] } = useQuery({
        queryKey: ["proposals"],
        queryFn: () => proposalsApi.list(),
    })

    const { data: clients = [] } = useQuery({
        queryKey: ["clients-all-active"],
        queryFn: () => clientsApi.listAll("active"),
    })

    const createMutation = useMutation({
        mutationFn: (data: ProposalCreate) => proposalsApi.create(data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setDialogOpen(false)
            toast.success("Propuesta creada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al crear la propuesta")),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: ProposalUpdate }) => proposalsApi.update(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setDialogOpen(false)
            toast.success("Propuesta actualizada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar la propuesta")),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: number) => proposalsApi.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setDeleteId(null)
            toast.success("Propuesta eliminada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar la propuesta")),
    })

    const openCreate = () => {
        setEditing(null)
        setTitle("")
        setClientId("")
        setStatus("draft")
        setBudget("")
        setScope("")
        setValidDays("30")
        setDialogOpen(true)
    }

    const openEdit = (p: Proposal) => {
        setEditing(p)
        setTitle(p.title)
        setClientId(p.client_id)
        setStatus(p.status)
        setBudget(p.budget !== null ? p.budget.toString() : "")
        setScope(p.scope || "")
        setValidDays("30")
        setDialogOpen(true)
    }

    const handleSave = () => {
        if (!title || clientId === "") {
            toast.error("El título y el cliente son obligatorios")
            return
        }

        const payload: ProposalCreate = {
            title,
            client_id: Number(clientId),
            status,
            budget: budget ? parseFloat(budget) : null,
            scope: scope || null,
            // Calculate valid until if validDays is set
            valid_until: validDays ? new Date(Date.now() + parseInt(validDays) * 24 * 60 * 60 * 1000).toISOString() : null
        }

        if (editing) {
            updateMutation.mutate({ id: editing.id, data: payload })
        } else {
            createMutation.mutate(payload)
        }
    }

    const downloadPdf = async (id: number, e: React.MouseEvent) => {
        e.stopPropagation()
        try {
            toast.loading("Generando PDF...", { id: "pdf" })
            const blob = await proposalsApi.downloadPdf(id)
            const url = window.URL.createObjectURL(new Blob([blob]))
            const link = document.createElement("a")
            link.href = url
            link.setAttribute("download", `Propuesta_${id}.pdf`)
            document.body.appendChild(link)
            link.click()
            link.remove()
            toast.success("PDF generado", { id: "pdf" })
        } catch (error) {
            toast.error("Error al generar el PDF", { id: "pdf" })
        }
    }

    return (
        <div className="space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">Propuestas</h1>
                    <p className="text-muted-foreground mt-1">
                        Gestiona y genera presupuestos en PDF para tus clientes.
                    </p>
                </div>
                <Button onClick={openCreate} className="w-full sm:w-auto">
                    <Plus className="w-4 h-4 mr-2" /> Nueva Propuesta
                </Button>
            </div>

            <Card>
                <CardContent className="p-0">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Título</TableHead>
                                <TableHead>Cliente</TableHead>
                                <TableHead>Estado</TableHead>
                                <TableHead>Presupuesto</TableHead>
                                <TableHead>Fecha</TableHead>
                                <TableHead className="text-right">Acciones</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {proposals.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                                        <FileText className="w-8 h-8 mx-auto mb-3 opacity-20" />
                                        No hay propuestas registradas.
                                    </TableCell>
                                </TableRow>
                            ) : (
                                proposals.map((p) => (
                                    <TableRow key={p.id} className="cursor-pointer hover:bg-muted/50" onClick={() => openEdit(p)}>
                                        <TableCell className="font-medium">{p.title}</TableCell>
                                        <TableCell>{p.client_name}</TableCell>
                                        <TableCell>
                                            <Badge variant={statusConfig[p.status].variant}>
                                                {statusConfig[p.status].label}
                                            </Badge>
                                        </TableCell>
                                        <TableCell>
                                            {p.budget ? `${p.budget.toLocaleString("es-ES")} €` : "A convenir"}
                                        </TableCell>
                                        <TableCell>
                                            {format(new Date(p.created_at), "dd/MM/yyyy")}
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <div className="flex justify-end gap-2">
                                                <Button variant="ghost" size="sm" onClick={(e) => downloadPdf(p.id, e)} title="Descargar PDF">
                                                    <Download className="w-4 h-4 text-brand" />
                                                </Button>
                                                <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); setDeleteId(p.id) }}>
                                                    <Trash2 className="w-4 h-4 text-destructive" />
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ))
                            )}
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>

            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogHeader>
                    <DialogTitle>{editing ? "Editar Propuesta" : "Nueva Propuesta"}</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 pt-4">
                    <div className="space-y-2">
                        <Label>Título *</Label>
                        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ej. Auditoría SEO Avanzada" />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <Label>Cliente *</Label>
                            <Select value={clientId.toString()} onChange={(e) => setClientId(Number(e.target.value))}>
                                <option value="" disabled>Seleccionar cliente</option>
                                {clients.map((c) => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </Select>
                        </div>
                        <div className="space-y-2">
                            <Label>Estado</Label>
                            <Select value={status} onChange={(e) => setStatus(e.target.value as ProposalStatus)}>
                                <option value="draft">Borrador</option>
                                <option value="sent">Enviada</option>
                                <option value="accepted">Aceptada</option>
                                <option value="rejected">Rechazada</option>
                            </Select>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <Label>Presupuesto Estimado (€)</Label>
                            <Input type="number" step="0.01" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="Ej. 1500" />
                        </div>
                        <div className="space-y-2">
                            <Label>Validez (días)</Label>
                            <Input type="number" value={validDays} onChange={(e) => setValidDays(e.target.value)} placeholder="30" />
                        </div>
                    </div>

                    <div className="space-y-2">
                        <Label>Alcance (Aparecerá en el PDF)</Label>
                        <Textarea
                            className="min-h-[150px] font-mono text-sm"
                            value={scope}
                            onChange={(e) => setScope(e.target.value)}
                            placeholder="Detalla los entregables, cronograma y condiciones del servicio..."
                        />
                    </div>

                    <div className="flex justify-end pt-4 gap-2">
                        <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
                        <Button onClick={handleSave} disabled={createMutation.isPending || updateMutation.isPending}>
                            {editing ? "Guardar" : "Crear"}
                        </Button>
                    </div>
                </div>
            </Dialog>

            <ConfirmDialog
                open={!!deleteId}
                onOpenChange={(open) => !open && setDeleteId(null)}
                title="Eliminar Propuesta"
                description="¿Estás seguro de que deseas eliminar esta propuesta? Esta acción no se puede deshacer."
                onConfirm={() => deleteMutation.mutate(deleteId!)}
            />
        </div>
    )
}
