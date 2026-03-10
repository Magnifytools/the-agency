import { useEffect } from "react"

interface BottomDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}

export function BottomDrawer({ open, onOpenChange, children }: BottomDrawerProps) {
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden"
      return () => { document.body.style.overflow = "" }
    }
  }, [open])

  if (!open) return null

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-[60]" onClick={() => onOpenChange(false)} />
      <div className="fixed bottom-0 left-0 right-0 bg-card border-t rounded-t-2xl max-h-[70vh] overflow-y-auto p-4 pb-8 z-[61]">
        <div className="w-10 h-1 bg-muted-foreground/30 rounded-full mx-auto mb-4" />
        {children}
      </div>
    </>
  )
}
