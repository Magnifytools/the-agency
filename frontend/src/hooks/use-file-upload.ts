import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { AxiosError, type AxiosProgressEvent } from "axios"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

export type UploadProgressHandler = (event: AxiosProgressEvent) => void

export interface UploadState {
  name: string
  /** 0-100, o null si el navegador no sabe el tamaño total. */
  percent: number | null
}

/** Motivo legible de un fallo de subida: el `detail` del servidor si lo hay. */
export function uploadErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail !== "string" || !detail) {
      if (error.response?.status === 413) return "El archivo es demasiado grande"
      if (!error.response) return "Se cortó la conexión durante la subida"
    }
  }
  return getErrorMessage(error, "Error inesperado")
}

/**
 * Sube un archivo enseñando en qué punto está: progreso mientras sube, toast
 * al terminar y toast con el motivo real del servidor si falla.
 */
export function useFileUpload<T>({
  upload,
  onUploaded,
}: {
  upload: (file: File, onProgress: UploadProgressHandler) => Promise<T>
  onUploaded?: (result: T, file: File) => void
}) {
  const [state, setState] = useState<UploadState | null>(null)
  const mutation = useMutation({
    mutationFn: (file: File) =>
      upload(file, (event) =>
        setState({
          name: file.name,
          percent: event.total ? Math.min(100, Math.round((event.loaded * 100) / event.total)) : null,
        }),
      ),
    onMutate: (file) => setState({ name: file.name, percent: 0 }),
    onSuccess: (result, file) => {
      toast.success(`«${file.name}» subido`)
      onUploaded?.(result, file)
    },
    onError: (error, file) => toast.error(`No se pudo subir «${file.name}»: ${uploadErrorMessage(error)}`),
    onSettled: () => setState(null),
  })
  return { upload: mutation.mutate, uploading: state, isUploading: mutation.isPending }
}
