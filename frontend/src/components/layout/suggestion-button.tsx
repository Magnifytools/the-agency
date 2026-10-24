import { useEffect, useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useLocation, useNavigate } from "react-router-dom"
import { ImagePlus, Lightbulb, Loader2, X } from "lucide-react"
import { toast } from "sonner"
import { suggestionsApi } from "@/lib/api"
import { suggestionKeys } from "@/lib/query-keys"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { IMAGE_TYPES, MAX_IMAGES, acceptImages } from "@/lib/suggestion-images"

const MAX_TEXT = 4000

export function SuggestionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [text, setText] = useState("")
  // Cada imagen con su URL local para la miniatura (se libera al quitarla o al cerrar).
  const [images, setImages] = useState<{ file: File; url: string }[]>([])
  const [imageProblem, setImageProblem] = useState<string | null>(null)
  const [uploaded, setUploaded] = useState(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const latest = useRef(images)
  useEffect(() => {
    latest.current = images
  }, [images])
  useEffect(() => () => latest.current.forEach((image) => URL.revokeObjectURL(image.url)), [])
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isAdmin } = useAuth()

  const addImages = (incoming: File[]) => {
    const { files, problem } = acceptImages(images.map((image) => image.file), incoming)
    const added = files.slice(images.length).map((file) => ({ file, url: URL.createObjectURL(file) }))
    setImages([...images, ...added])
    setImageProblem(problem)
  }
  const removeImage = (index: number) => {
    URL.revokeObjectURL(images[index].url)
    setImages(images.filter((_, i) => i !== index))
  }

  const send = useMutation({
    mutationFn: async () => {
      const created = await suggestionsApi.create({ text: text.trim(), page_path: `${location.pathname}${location.search}` })
      // La sugerencia ya está guardada: si una imagen falla, se dice cuántas no entraron.
      let failed = 0
      setUploaded(0)
      for (const image of images) {
        try {
          await suggestionsApi.addImage(created.id, image.file)
        } catch {
          failed += 1
        }
        setUploaded((n) => n + 1)
      }
      return failed
    },
    onSuccess: (failed) => {
      setText("")
      images.forEach((image) => URL.revokeObjectURL(image.url))
      setImages([])
      setImageProblem(null)
      onOpenChange(false)
      void queryClient.invalidateQueries({ queryKey: suggestionKeys.all })
      const action = { label: isAdmin ? "Ver todas" : "Ver las mías", onClick: () => navigate("/sugerencias") }
      if (failed) toast.warning(`Sugerencia enviada, pero ${failed === 1 ? "una imagen no se pudo subir" : `${failed} imágenes no se pudieron subir`}.`, { action })
      else toast.success("Sugerencia enviada. ¡Gracias!", { action })
    },
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo enviar la sugerencia")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-brand" />
          Sugerencias y fallos
        </DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (text.trim() && !send.isPending) send.mutate()
        }}
        // Un pantallazo pegado (⌘V / Ctrl+V) entra como imagen adjunta.
        onPaste={(event) => {
          const pasted = Array.from(event.clipboardData?.files ?? []).filter((file) => file.type.startsWith("image/"))
          if (pasted.length) {
            event.preventDefault()
            addImages(pasted)
          }
        }}
      >
        <DialogContent>
          <label htmlFor="suggestion-text" className="text-sm text-muted-foreground block mb-2">
            Una idea para mejorar la app o algo que no funciona. Llega a los administradores y aquí verás en qué queda.
          </label>
          <Textarea
            id="suggestion-text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={MAX_TEXT}
            rows={6}
            autoFocus
            placeholder="Ej.: al subir un informe en HTML no pasa nada"
          />
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={images.length >= MAX_IMAGES || send.isPending}
                onClick={() => fileInput.current?.click()}
              >
                <ImagePlus className="h-4 w-4 mr-1" /> Añadir pantallazo
              </Button>
              <span className="text-xs text-muted-foreground">o pégalo aquí con ⌘V · hasta {MAX_IMAGES}, 5 MB cada uno</span>
              <input
                ref={fileInput}
                type="file"
                accept={IMAGE_TYPES.join(",")}
                multiple
                className="hidden"
                aria-label="Pantallazos"
                onChange={(event) => {
                  addImages(Array.from(event.target.files ?? []))
                  event.target.value = ""
                }}
              />
            </div>
            {imageProblem && <p role="alert" className="text-xs text-destructive">{imageProblem}</p>}
            {images.length > 0 && (
              <ul className="flex flex-wrap gap-2" aria-label="Pantallazos adjuntos">
                {images.map((image, index) => (
                  <li key={image.url} className="relative">
                    <img src={image.url} alt={image.file.name || `Pantallazo ${index + 1}`} className="h-16 w-24 rounded-md border border-border object-cover" />
                    <button
                      type="button"
                      aria-label={`Quitar ${image.file.name || `pantallazo ${index + 1}`}`}
                      disabled={send.isPending}
                      onClick={() => removeImage(index)}
                      className="absolute -right-1.5 -top-1.5 rounded-full bg-background border border-border p-0.5 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </DialogContent>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!text.trim() || send.isPending}>
            {send.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            {send.isPending && images.length ? `Subiendo ${Math.min(uploaded + 1, images.length)}/${images.length}…` : "Enviar"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  )
}

/** Botón de la barra lateral (y del menú de cuenta en móvil) que abre el diálogo. */
export function SuggestionButton({ showLabel = false }: { showLabel?: boolean } = {}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={
          showLabel
            ? "flex min-h-11 w-full flex-col items-center justify-center gap-1 rounded-lg p-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            : "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        }
      >
        <Lightbulb className="h-4 w-4" />
        {showLabel ? "Sugerencias" : "Sugerencias o fallos"}
      </button>
      <SuggestionDialog open={open} onOpenChange={setOpen} />
    </>
  )
}
