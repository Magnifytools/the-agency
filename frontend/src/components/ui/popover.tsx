import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode, type Ref } from "react"
import {
  FloatingFocusManager, FloatingPortal, autoUpdate, flip, offset, shift, size,
  useClick, useDismiss, useFloating, useInteractions, useRole, type Placement,
} from "@floating-ui/react"
import { cn } from "@/lib/utils"

export interface PopoverTriggerProps {
  ref: Ref<HTMLButtonElement>
  props: ButtonHTMLAttributes<HTMLButtonElement>
  open: boolean
}

interface PopoverProps {
  /** Nombre accesible del panel flotante. */
  label: string
  trigger: (trigger: PopoverTriggerProps) => ReactNode
  children: (close: () => void) => ReactNode
  placement?: Placement
  className?: string
}

/**
 * Panel flotante anclado a un botón: posición (se da la vuelta y se desplaza si
 * no cabe), cierre con Escape o clic fuera y foco dentro mientras está abierto
 * (al cerrar vuelve al botón). Base de los editores en línea.
 */
export function Popover({ label, trigger, children, placement = "bottom-start", className }: PopoverProps) {
  const [open, setOpen] = useState(false)
  const { refs: { setReference, setFloating }, elements, floatingStyles, context } = useFloating({
    open,
    onOpenChange: setOpen,
    placement,
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(4),
      flip({ padding: 8 }),
      shift({ padding: 8 }),
      size({
        padding: 8,
        apply({ availableHeight, elements }) {
          elements.floating.style.maxHeight = `${Math.max(160, availableHeight)}px`
        },
      }),
    ],
  })
  const { getReferenceProps, getFloatingProps } = useInteractions([
    useClick(context),
    useDismiss(context),
    useRole(context, { role: "dialog" }),
  ])
  const close = () => setOpen(false)
  // Foco inicial: la opción elegida si la hay (Enter la deja como estaba); si
  // no, lo primero que se pueda usar. Un campo con autoFocus ya lo tiene.
  const floating = elements.floating
  useEffect(() => {
    if (!open || !floating || floating.contains(document.activeElement)) return
    const target = floating.querySelector<HTMLElement>('[aria-selected="true"]')
      ?? floating.querySelector<HTMLElement>("button:not([disabled]), input")
    target?.focus()
  }, [open, floating])

  return (
    <>
      {trigger({
        ref: setReference,
        // El botón vive a menudo dentro de una fila o tarjeta que abre la tarea al
        // pulsarla: el clic se queda aquí.
        props: getReferenceProps({ onClick: (event) => event.stopPropagation() }) as ButtonHTMLAttributes<HTMLButtonElement>,
        open,
      })}
      {open && (
        <FloatingPortal>
          <FloatingFocusManager context={context} modal={false} initialFocus={-1} returnFocus>
            <div
              ref={setFloating}
              style={floatingStyles}
              aria-label={label}
              className={cn("z-[70] min-w-48 overflow-y-auto rounded-lg border border-border bg-card p-1 text-sm shadow-xl", className)}
              {...getFloatingProps({ onClick: (event) => event.stopPropagation() })}
            >
              {children(close)}
            </div>
          </FloatingFocusManager>
        </FloatingPortal>
      )}
    </>
  )
}
