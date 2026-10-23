import { Tag } from "lucide-react"
import type { Client } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"

/**
 * Aviso en la ficha mientras un cliente activo con Search Console no tenga
 * términos de marca: sin ellos, Control SEO no separa las búsquedas de marca
 * de las demás. Desaparece en cuanto se guarda alguno.
 */
export function BrandTermsNotice({ client, onConfigure }: { client: Client; onConfigure: () => void }) {
  const { hasPermission } = useAuth()
  if (client.status !== "active" || !client.gsc_url || (client.brand_terms ?? []).length > 0) return null
  const canWrite = hasPermission("clients", true)
  return (
    <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
      <p className="flex items-center gap-2">
        <Tag className="h-4 w-4 shrink-0 text-amber-600" />
        Faltan los términos de marca de {client.name}: sin ellos, Control SEO no separa las búsquedas de marca.
      </p>
      {canWrite && <Button size="sm" variant="outline" onClick={onConfigure}>Poner términos de marca</Button>}
    </div>
  )
}
