import * as React from "react"
import { createPortal } from "react-dom"
import { cn } from "@/lib/utils"
import { X } from "lucide-react"

let dialogIdCounter = 0

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}

function visibleFocusable(panel: HTMLElement) {
  return Array.from(panel.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
  )).filter((element) => {
    for (let ancestor: HTMLElement | null = element; ancestor && ancestor !== panel; ancestor = ancestor.parentElement) {
      if (ancestor.hidden || getComputedStyle(ancestor).display === "none" || getComputedStyle(ancestor).visibility === "hidden") return false
      if (ancestor instanceof HTMLDetailsElement && !ancestor.open && !ancestor.querySelector(":scope > summary")?.contains(element)) return false
    }
    return true
  })
}

function Dialog({ open, onOpenChange, children }: DialogProps) {
  const titleId = React.useMemo(() => `dialog-title-${++dialogIdCounter}`, [])
  const panelRef = React.useRef<HTMLDivElement>(null)
  const previouslyFocused = React.useRef<HTMLElement | null>(null)

  // Escape key + focus trap (Tab/Shift+Tab cycling within the panel)
  React.useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault()
        e.stopPropagation()
        onOpenChange(false)
        return
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = visibleFocusable(panelRef.current)
        if (focusable.length === 0) {
          e.preventDefault()
          return
        }
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        const active = document.activeElement as HTMLElement | null
        if (e.shiftKey) {
          if (active === first || !panelRef.current.contains(active)) {
            e.preventDefault()
            last.focus()
          }
        } else {
          if (active === last || !panelRef.current.contains(active)) {
            e.preventDefault()
            first.focus()
          }
        }
      }
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [open, onOpenChange])

  // Body scroll lock + focus management (focus first on open, restore on close)
  React.useEffect(() => {
    if (!open) return
    previouslyFocused.current = document.activeElement as HTMLElement | null
    document.body.style.overflow = "hidden"
    // Focus first focusable element inside the panel on open
    const focusFirst = () => {
      const panel = panelRef.current
      if (!panel) return
      // Preserve autofocus and any user interaction that happened before this frame.
      if (panel.contains(document.activeElement)) return
      const focusable = visibleFocusable(panel)
      if (focusable.length > 0) focusable[0].focus()
      else panel.focus()
    }
    const raf = requestAnimationFrame(focusFirst)
    return () => {
      cancelAnimationFrame(raf)
      document.body.style.overflow = ""
      previouslyFocused.current?.focus?.()
    }
  }, [open])

  if (!open) return null
  return createPortal(
    <DialogContext.Provider value={{ titleId }}>
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-2 sm:p-4">
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm"
          onClick={() => onOpenChange(false)}
        />
        <div
          ref={panelRef}
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className="relative z-50 w-full max-w-lg max-h-[90vh] md:max-h-[85vh] overflow-y-auto rounded-[16px] border border-border bg-card p-6 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => onOpenChange(false)}
            className="absolute right-4 top-4 text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm"
            aria-label="Cerrar"
          >
            <X className="h-4 w-4" />
          </button>
          {children}
        </div>
      </div>
    </DialogContext.Provider>,
    document.body,
  )
}

const DialogContext = React.createContext<{ titleId: string }>({ titleId: "" })

function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col space-y-1.5 text-center sm:text-left mb-4", className)} {...props} />
}

function DialogTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  const { titleId } = React.useContext(DialogContext)
  return <h2 id={titleId} className={cn("text-lg font-semibold leading-none tracking-tight text-foreground", className)} {...props} />
}

function DialogContent({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-4", className)} {...props}>{children}</div>
}

function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex justify-end gap-2 mt-4", className)} {...props} />
}

export { Dialog, DialogHeader, DialogTitle, DialogContent, DialogFooter }
