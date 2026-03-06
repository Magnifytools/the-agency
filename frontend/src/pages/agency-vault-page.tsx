import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { vaultApi } from "@/lib/api"
import { vaultKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import type { AgencyAsset, AgencyAssetCreate, AssetCategory, HostingType } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Archive, Plus, Pencil, Trash2, Mail, Globe, Server, Wrench, Eye, EyeOff } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { cn } from "@/lib/utils"

const TABS = [
  { key: "emails", label: "Emails", category: "email" as AssetCategory, icon: Mail },
  { key: "dominios", label: "Dominios", category: "domain" as AssetCategory, icon: Globe },
  { key: "hostings", label: "Hostings", category: "hosting" as AssetCategory, icon: Server },
  { key: "herramientas", label: "Herramientas", category: "tool" as AssetCategory, icon: Wrench },
] as const

const HOSTING_TYPES: { value: HostingType; label: string }[] = [
  { value: "shared", label: "Shared" },
  { value: "vps", label: "VPS" },
  { value: "dedicated", label: "Dedicated" },
  { value: "cloud", label: "Cloud" },
  { value: "other", label: "Otro" },
]

const SUBSCRIPTION_TYPES = ["Gratuita", "Mensual", "Anual", "De pago", "Trial"]

const emptyForm: AgencyAssetCreate = {
  category: "email",
  name: "",
  value: "",
  provider: "",
  url: "",
  notes: "",
  associated_domain: "",
  registrar: "",
  expiry_date: "",
  auto_renew: false,
  dns_provider: "",
  hosting_type: null,
  tool_category: "",
  monthly_cost: null,
  username: "",
  password: "",
  is_active: null,
  subscription_type: "",
  purpose: "",
}

export default function AgencyVaultPage() {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  const activeTab = searchParams.get("tab") || "emails"
  const currentTab = TABS.find((t) => t.key === activeTab) ?? TABS[0]

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<AgencyAsset | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [formData, setFormData] = useState<AgencyAssetCreate>({ ...emptyForm })

  const { data: assets = [], isLoading } = useQuery({
    queryKey: vaultKeys.assets(currentTab.category),
    queryFn: () => vaultApi.list(currentTab.category),
  })

  const createMutation = useMutation({
    mutationFn: (data: AgencyAssetCreate) => vaultApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vault-assets"] })
      closeDialog()
      toast.success("Recurso creado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear")),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<AgencyAssetCreate> }) => vaultApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vault-assets"] })
      closeDialog()
      toast.success("Recurso actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => vaultApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vault-assets"] })
      setDeleteId(null)
      toast.success("Recurso eliminado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
  })

  function closeDialog() {
    setDialogOpen(false)
    setEditing(null)
    setFormData({ ...emptyForm })
  }

  function openCreate() {
    setEditing(null)
    setFormData({ ...emptyForm, category: currentTab.category })
    setDialogOpen(true)
  }

  function openEdit(asset: AgencyAsset) {
    setEditing(asset)
    setFormData({
      category: asset.category,
      name: asset.name,
      value: asset.value ?? "",
      provider: asset.provider ?? "",
      url: asset.url ?? "",
      notes: asset.notes ?? "",
      associated_domain: asset.associated_domain ?? "",
      registrar: asset.registrar ?? "",
      expiry_date: asset.expiry_date ?? "",
      auto_renew: asset.auto_renew,
      dns_provider: asset.dns_provider ?? "",
      hosting_type: asset.hosting_type,
      tool_category: asset.tool_category ?? "",
      monthly_cost: asset.monthly_cost,
      username: asset.username ?? "",
      password: "",  // never pre-filled from API — only set when updating
      is_active: asset.is_active,
      subscription_type: asset.subscription_type ?? "",
      purpose: asset.purpose ?? "",
    })
    setDialogOpen(true)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!formData.name) return
    // Clean empty strings to null
    const cleaned = { ...formData }
    for (const key of Object.keys(cleaned) as (keyof AgencyAssetCreate)[]) {
      if (cleaned[key] === "") (cleaned as Record<string, unknown>)[key] = null
    }
    if (editing) {
      updateMutation.mutate({ id: editing.id, data: cleaned })
    } else {
      createMutation.mutate(cleaned)
    }
  }

  const setTab = (key: string) => setSearchParams({ tab: key })

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Archive className="h-6 w-6 text-brand" />
            Agency Vault
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Recursos internos de la agencia
          </p>
        </div>
        {isAdmin && (
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4 mr-2" />
            Nuevo
          </Button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-muted/50 rounded-xl p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setTab(tab.key)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all flex-1 justify-center",
              activeTab === tab.key
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="grid sm:grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i} className="p-5 animate-pulse">
              <div className="h-4 bg-muted rounded w-3/4 mb-3" />
              <div className="h-3 bg-muted rounded w-1/2" />
            </Card>
          ))}
        </div>
      ) : assets.length === 0 ? (
        <Card className="p-12 flex flex-col items-center text-center">
          <currentTab.icon className="h-10 w-10 text-muted-foreground/30 mb-3" />
          <p className="text-sm font-medium text-foreground mb-1">Sin {currentTab.label.toLowerCase()}</p>
          <p className="text-xs text-muted-foreground">
            {isAdmin ? "Pulsa \"Nuevo\" para añadir el primero." : "No hay recursos en esta categoría."}
          </p>
        </Card>
      ) : (
        <div className="grid sm:grid-cols-2 gap-4">
          {assets.map((asset) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              category={currentTab.category}
              isAdmin={isAdmin}
              onEdit={() => openEdit(asset)}
              onDelete={() => setDeleteId(asset.id)}
            />
          ))}
        </div>
      )}

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={(open) => { if (!open) closeDialog() }}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar recurso" : "Nuevo recurso"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          {/* Common fields */}
          <div className="space-y-2">
            <Label>Nombre *</Label>
            <Input
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="Nombre identificativo"
              required
            />
          </div>

          {/* Category-specific fields */}
          {currentTab.category === "email" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Email</Label>
                  <Input
                    type="email"
                    value={formData.value ?? ""}
                    onChange={(e) => setFormData({ ...formData, value: e.target.value })}
                    placeholder="user@dominio.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Contraseña</Label>
                  <Input
                    type="password"
                    value={formData.password ?? ""}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    placeholder="••••••••"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Uso / Propósito</Label>
                  <Input
                    value={formData.purpose ?? ""}
                    onChange={(e) => setFormData({ ...formData, purpose: e.target.value })}
                    placeholder="Contacto general, Cuentas herramientas..."
                  />
                </div>
                <div className="space-y-2">
                  <Label>URL de acceso</Label>
                  <Input
                    value={formData.url ?? ""}
                    onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                    placeholder="https://webmail.proveedor.com"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Proveedor</Label>
                  <Input
                    value={formData.provider ?? ""}
                    onChange={(e) => setFormData({ ...formData, provider: e.target.value })}
                    placeholder="Google Workspace, Siteground..."
                  />
                </div>
                <div className="space-y-2">
                  <Label>Dominio asociado</Label>
                  <Input
                    value={formData.associated_domain ?? ""}
                    onChange={(e) => setFormData({ ...formData, associated_domain: e.target.value })}
                    placeholder="dominio.com"
                  />
                </div>
              </div>
            </>
          )}

          {currentTab.category === "domain" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Dominio</Label>
                  <Input
                    value={formData.value ?? ""}
                    onChange={(e) => setFormData({ ...formData, value: e.target.value })}
                    placeholder="dominio.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Registrar</Label>
                  <Input
                    value={formData.registrar ?? ""}
                    onChange={(e) => setFormData({ ...formData, registrar: e.target.value })}
                    placeholder="Namecheap, GoDaddy..."
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Fecha expiración</Label>
                  <Input
                    type="date"
                    value={formData.expiry_date ?? ""}
                    onChange={(e) => setFormData({ ...formData, expiry_date: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label>DNS Provider</Label>
                  <Input
                    value={formData.dns_provider ?? ""}
                    onChange={(e) => setFormData({ ...formData, dns_provider: e.target.value })}
                    placeholder="Cloudflare, Route53..."
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={formData.auto_renew ?? false}
                  onChange={(e) => setFormData({ ...formData, auto_renew: e.target.checked })}
                  className="rounded border-border"
                />
                Auto-renovación activa
              </label>
            </>
          )}

          {currentTab.category === "hosting" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Proveedor</Label>
                  <Input
                    value={formData.provider ?? ""}
                    onChange={(e) => setFormData({ ...formData, provider: e.target.value })}
                    placeholder="AWS, DigitalOcean, Vercel..."
                  />
                </div>
                <div className="space-y-2">
                  <Label>Tipo</Label>
                  <Select
                    value={formData.hosting_type ?? ""}
                    onChange={(e) => setFormData({ ...formData, hosting_type: (e.target.value || null) as HostingType | null })}
                  >
                    <option value="">Seleccionar...</option>
                    {HOSTING_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>URL</Label>
                  <Input
                    value={formData.url ?? ""}
                    onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                    placeholder="https://panel.proveedor.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Coste mensual</Label>
                  <Input
                    type="number"
                    step="0.01"
                    min="0"
                    value={formData.monthly_cost ?? ""}
                    onChange={(e) => setFormData({ ...formData, monthly_cost: e.target.value ? Number(e.target.value) : null })}
                    placeholder="0.00"
                  />
                </div>
              </div>
            </>
          )}

          {currentTab.category === "tool" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Usuario / Email</Label>
                  <Input
                    value={formData.username ?? ""}
                    onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                    placeholder="digital@magnify.ing"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Contraseña</Label>
                  <Input
                    type="password"
                    value={formData.password ?? ""}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    placeholder="••••••••"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Suscripción</Label>
                  <Select
                    value={formData.subscription_type ?? ""}
                    onChange={(e) => setFormData({ ...formData, subscription_type: e.target.value || null })}
                  >
                    <option value="">Sin especificar</option>
                    {SUBSCRIPTION_TYPES.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Categoría</Label>
                  <Input
                    value={formData.tool_category ?? ""}
                    onChange={(e) => setFormData({ ...formData, tool_category: e.target.value })}
                    placeholder="SEO, Analytics, Diseño..."
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>URL</Label>
                  <Input
                    value={formData.url ?? ""}
                    onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                    placeholder="https://herramienta.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Coste mensual</Label>
                  <Input
                    type="number"
                    step="0.01"
                    min="0"
                    value={formData.monthly_cost ?? ""}
                    onChange={(e) => setFormData({ ...formData, monthly_cost: e.target.value ? Number(e.target.value) : null })}
                    placeholder="0.00"
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={formData.is_active ?? false}
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                  className="rounded border-border"
                />
                Activa
              </label>
            </>
          )}

          {/* Notes - common to all */}
          <div className="space-y-2">
            <Label>Notas</Label>
            <Textarea
              value={formData.notes ?? ""}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              placeholder="Notas adicionales..."
              rows={2}
            />
          </div>

          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={closeDialog}>
              Cancelar
            </Button>
            <Button type="submit" disabled={createMutation.isPending || updateMutation.isPending || !formData.name}>
              {editing ? "Guardar" : "Crear"}
            </Button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Eliminar recurso"
        description="Esta acción no se puede deshacer. El recurso será eliminado permanentemente."
        onConfirm={() => {
          if (deleteId) deleteMutation.mutate(deleteId)
        }}
      />
    </div>
  )
}

// --- Password reveal field (fetches on demand) ---
function PasswordField({ assetId }: { assetId: number }) {
  const [show, setShow] = useState(false)
  const [password, setPassword] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleToggle = async () => {
    if (!show && password === null) {
      setLoading(true)
      try {
        const res = await vaultApi.getPassword(assetId)
        setPassword(res.password ?? "")
      } catch {
        setPassword("(error al obtener)")
      } finally {
        setLoading(false)
      }
    }
    setShow((v) => !v)
  }

  return (
    <div className="flex items-center gap-1 mt-0.5">
      <p className="text-xs font-mono text-muted-foreground truncate flex-1">
        {loading ? "Cargando..." : show && password !== null ? password : "••••••••••••"}
      </p>
      <button
        onClick={handleToggle}
        className="p-0.5 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
        title={show ? "Ocultar" : "Mostrar contraseña"}
      >
        {show ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
      </button>
    </div>
  )
}

// --- Asset Card per category ---

function AssetCard({
  asset,
  category,
  isAdmin,
  onEdit,
  onDelete,
}: {
  asset: AgencyAsset
  category: AssetCategory
  isAdmin: boolean
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <Card className="p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-foreground truncate">{asset.name}</p>
          {asset.value && (
            <p className="text-sm text-muted-foreground truncate mt-0.5">{asset.value}</p>
          )}
          {asset.username && asset.username !== asset.value && (
            <p className="text-xs text-muted-foreground truncate mt-0.5">👤 {asset.username}</p>
          )}
          {asset.has_password && (
            <PasswordField assetId={asset.id} />
          )}
        </div>
        {isAdmin && (
          <div className="flex gap-1 flex-shrink-0">
            <Button variant="ghost" size="sm" aria-label="Editar" className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground" onClick={onEdit}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="sm" aria-label="Eliminar" className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive" onClick={onDelete}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        {category === "email" && (
          <>
            {asset.purpose && <Badge variant="secondary">{asset.purpose}</Badge>}
            {asset.provider && <Badge variant="outline">{asset.provider}</Badge>}
            {asset.associated_domain && <Badge variant="outline">{asset.associated_domain}</Badge>}
          </>
        )}

        {category === "domain" && (
          <>
            {asset.registrar && <Badge variant="outline">{asset.registrar}</Badge>}
            {asset.dns_provider && <Badge variant="secondary">{asset.dns_provider}</Badge>}
            {asset.auto_renew && <Badge variant="success">Auto-renew</Badge>}
            {asset.expiry_date && (
              <Badge variant={isExpiringSoon(asset.expiry_date) ? "warning" : "outline"}>
                Exp: {asset.expiry_date}
              </Badge>
            )}
          </>
        )}

        {category === "hosting" && (
          <>
            {asset.provider && <Badge variant="outline">{asset.provider}</Badge>}
            {asset.hosting_type && <Badge variant="secondary">{asset.hosting_type}</Badge>}
            {asset.monthly_cost != null && (
              <Badge variant="default">{Number(asset.monthly_cost).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} /mes</Badge>
            )}
          </>
        )}

        {category === "tool" && (
          <>
            {asset.is_active != null && (
              <Badge variant={asset.is_active ? "success" : "outline"}>{asset.is_active ? "Activa" : "Inactiva"}</Badge>
            )}
            {asset.subscription_type && <Badge variant="secondary">{asset.subscription_type}</Badge>}
            {asset.tool_category && <Badge variant="outline">{asset.tool_category}</Badge>}
            {asset.monthly_cost != null && (
              <Badge variant="default">{Number(asset.monthly_cost).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} /mes</Badge>
            )}
          </>
        )}
      </div>

      {asset.url && category === "email" && (
        <a
          href={asset.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-brand hover:underline truncate"
        >
          🔗 {asset.url}
        </a>
      )}

      {asset.url && category !== "email" && (
        <a
          href={asset.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-brand hover:underline truncate"
        >
          {asset.url}
        </a>
      )}

      {asset.notes && (
        <p className="text-xs text-muted-foreground line-clamp-2">{asset.notes}</p>
      )}
    </Card>
  )
}

function isExpiringSoon(dateStr: string): boolean {
  const expiry = new Date(dateStr)
  const now = new Date()
  const diffDays = (expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
  return diffDays <= 30
}
