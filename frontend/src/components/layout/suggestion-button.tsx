import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useLocation, useNavigate } from "react-router-dom"
import { Lightbulb, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { suggestionsApi } from "@/lib/api"
import { suggestionKeys } from "@/lib/query-keys"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"

const MAX_TEXT = 4000

export function SuggestionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [text, setText] = useState("")
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isAdmin } = useAuth()

  const send = useMutation({
    mutationFn: () => suggestionsApi.create({ text: text.trim(), page_path: `${location.pathname}${location.search}` }),
    onSuccess: () => {
      setText("")
      onOpenChange(false)
      void queryClient.invalidateQueries({ queryKey: suggestionKeys.all })
      toast.success("Sugerencia enviada. ¡Gracias!", {
        action: { label: isAdmin ? "Ver todas" : "Ver las mías", onClick: () => navigate("/sugerencias") },
      })
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
        </DialogContent>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!text.trim() || send.isPending}>
            {send.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            Enviar
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
