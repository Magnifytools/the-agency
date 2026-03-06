import * as React from "react"
import { cn } from "@/lib/utils"
import { X } from "lucide-react"

let dialogIdCounter = 0

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}

function Dialog({ open, onOpenChange, children }: DialogProps) {
  const titleId = React.useMemo(() => `dialog-title-${++dialogIdCounter}`, [])
  if (!open) return null
  return (
    <DialogContext.Provider value={{ titleId }}>
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={() => onOpenChange(false)} />
        <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative z-50 w-full max-w-lg max-h-[90vh] md:max-h-[85vh] overflow-y-auto rounded-[16px] border border-border bg-card p-6 shadow-2xl">
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
    </DialogContext.Provider>
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
