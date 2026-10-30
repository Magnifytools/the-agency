import { useState } from "react"
import { FileDown, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { saveFile, type PdfFile } from "@/lib/pdf-download"
import { getErrorMessage } from "@/lib/utils"

interface Props {
  /** Pide el PDF (y, si hace falta, guarda antes). null = no descargar (ya se avisó). */
  download: () => Promise<PdfFile | null>
  /** Sólo el icono (filas de la lista); entonces aria-label es obligatorio. */
  iconOnly?: boolean
  ariaLabel?: string
  variant?: "default" | "outline" | "ghost"
  size?: "default" | "sm"
  disabled?: boolean
}

/** Con responseType "blob" el error del servidor (429, 504…) también llega como Blob. */
async function pdfErrorMessage(error: unknown): Promise<string> {
  const data = (error as { response?: { data?: unknown } })?.response?.data
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text()) as { detail?: unknown }
      if (typeof parsed.detail === "string") return parsed.detail
    } catch {
      // No era JSON: mensaje genérico.
    }
  }
  return getErrorMessage(error, "No se pudo generar el PDF")
}

/** La misma descarga desde un menú (el botón desaparece al elegir): avisa con un toast. */
export async function downloadPdfWithToast(download: () => Promise<PdfFile | null>) {
  const id = toast.loading("Generando PDF…")
  try {
    const file = await download()
    if (file) saveFile(file)
    toast.dismiss(id)
  } catch (error) {
    toast.error(await pdfErrorMessage(error), { id })
  }
}

/** "Descargar PDF" del resumen: lo mismo que recibe el cliente, en A4. */
export function DownloadPdfButton({ download, iconOnly = false, ariaLabel, variant = "outline", size = "default", disabled }: Props) {
  const [busy, setBusy] = useState(false)

  const handleClick = async () => {
    setBusy(true)
    try {
      const file = await download()
      if (file) saveFile(file)
    } catch (error) {
      toast.error(await pdfErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const icon = busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />
  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      title={iconOnly ? "Descargar PDF" : undefined}
      aria-label={ariaLabel}
      aria-busy={busy}
      disabled={disabled || busy}
      onClick={() => void handleClick()}
    >
      {icon}
      {!iconOnly && <span className="ml-2">{busy ? "Generando PDF…" : "Descargar PDF"}</span>}
    </Button>
  )
}
