import * as React from "react"
import { createPortal } from "react-dom"
import { HelpCircle } from "lucide-react"
import { cn } from "@/lib/utils"

interface TooltipProps {
  content: React.ReactNode
  children: React.ReactNode
  side?: "top" | "bottom"
  align?: "start" | "center" | "end"
  className?: string
}

export function Tooltip({ content, children, side = "bottom", align = "center", className }: TooltipProps) {
  const [open, setOpen] = React.useState(false)
  const triggerRef = React.useRef<HTMLSpanElement>(null)
  const [pos, setPos] = React.useState({ top: 0, left: 0 })

  React.useEffect(() => {
    if (open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const top = side === "bottom" ? rect.bottom + 8 : rect.top - 8
      const left = align === "end" ? rect.right : align === "start" ? rect.left : rect.left + rect.width / 2
      setPos({ top, left })
    }
  }, [open, side, align])

  const transformClass =
    align === "start" ? "translate-x-0" :
    align === "end" ? "-translate-x-full" :
    "-translate-x-1/2"

  return (
    <span
      ref={triggerRef}
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onClick={() => setOpen((v) => !v)}
    >
      {children}
      {open && createPortal(
        <span
          role="tooltip"
          style={{ top: pos.top, left: pos.left, position: "fixed" }}
          className={cn(
            "z-[9999] w-max max-w-[260px] rounded-[10px] border border-border bg-surface px-3 py-2 text-xs leading-relaxed text-foreground shadow-lg pointer-events-none",
            side === "top" && "-translate-y-full",
            transformClass,
            className
          )}
        >
          {content}
        </span>,
        document.body
      )}
    </span>
  )
}

export function InfoTooltip({ content, align = "end", className }: { content: React.ReactNode; align?: "start" | "center" | "end"; className?: string }) {
  return (
    <Tooltip content={content} align={align} className={className}>
      <HelpCircle className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
    </Tooltip>
  )
}
