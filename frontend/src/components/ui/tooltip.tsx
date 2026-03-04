import * as React from "react"
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

  const alignClass =
    align === "start" ? "left-0" :
    align === "end" ? "right-0" :
    "left-1/2 -translate-x-1/2"

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onClick={() => setOpen((v) => !v)}
    >
      {children}
      {open && (
        <span
          role="tooltip"
          className={cn(
            "absolute z-50 w-max max-w-[260px] rounded-[10px] border border-border bg-surface px-3 py-2 text-xs leading-relaxed text-foreground shadow-lg pointer-events-none",
            side === "bottom" ? "top-full mt-2" : "bottom-full mb-2",
            alignClass,
            className
          )}
        >
          {content}
        </span>
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
