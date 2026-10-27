import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { MoreHorizontal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export interface ActionMenuItem {
  label: string
  icon?: ReactNode
  onSelect: () => void
  destructive?: boolean
  disabled?: boolean
}

/**
 * Menú "Más" para las acciones secundarias de una fila. Se posiciona fijo
 * (no lo recorta el overflow de la tabla) y se cierra al elegir, con Escape o
 * con un clic fuera.
 */
export function ActionMenu({ label, items }: { label: string; items: ActionMenuItem[] }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<{ top: number; right: number }>({ top: 0, right: 0 })
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    menuRef.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus()
    const outside = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node) && !triggerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); triggerRef.current?.focus() }
    }
    const close = () => setOpen(false)
    document.addEventListener("mousedown", outside)
    document.addEventListener("keydown", key)
    window.addEventListener("resize", close)
    window.addEventListener("scroll", close, true)
    return () => {
      document.removeEventListener("mousedown", outside)
      document.removeEventListener("keydown", key)
      window.removeEventListener("resize", close)
      window.removeEventListener("scroll", close, true)
    }
  }, [open])

  const toggle = () => {
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      setPosition({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) })
    }
    setOpen(!open)
  }

  return (
    <>
      <Button ref={triggerRef} type="button" variant="ghost" size="sm" aria-label={label} title="Más acciones"
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} onClick={toggle}>
        <MoreHorizontal className="w-4 h-4" />
      </Button>
      {open && (
        <div ref={menuRef} id={menuId} role="menu" aria-label={label} style={position}
          className="fixed z-50 min-w-52 rounded-lg border border-border bg-card p-1 shadow-xl">
          {items.map((item) => (
            <button key={item.label} type="button" role="menuitem" disabled={item.disabled}
              onClick={() => { setOpen(false); item.onSelect() }}
              className={cn("flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-50",
                item.destructive && "text-destructive")}>
              {item.icon}{item.label}
            </button>
          ))}
        </div>
      )}
    </>
  )
}
