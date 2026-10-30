/** Un PDF descargado con axios (blob) para no perder la sesión, y su nombre. */
export interface PdfFile {
  blob: Blob
  filename: string
}

/** Nombre del fichero desde Content-Disposition (el backend lo manda en ASCII). */
export function filenameFromDisposition(header: unknown, fallback: string): string {
  const match = typeof header === "string" ? /filename="?([^";]+)"?/i.exec(header) : null
  return match?.[1]?.trim() || fallback
}

/** Guarda el blob con su nombre mediante un enlace temporal. */
export function saveFile({ blob, filename }: PdfFile): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
