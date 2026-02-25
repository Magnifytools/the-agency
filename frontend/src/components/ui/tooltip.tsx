import * as React from "react"
import { HelpCircle } from "lucide-react"
import { cn } from "@/lib/utils"

interface TooltipProps {
  content: React.ReactNode
  children: React.ReactNode
  side?: "top" | "bottom"
  className?: string
}

export function Tooltip({ content, children, side = "bottom", className }: TooltipProps) {
  const [open, setOpen] = React.useState(false)

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
            "absolute left-1/2 -translate-x-1/2 z-50 w-max max-w-[280px] rounded-[10px] border border-border bg-surface px-3 py-2 text-xs leading-relaxed text-foreground shadow-lg",
            "animate-in fade-in-0 zoom-in-95 duration-150",
            side === "bottom" ? "top-full mt-2" : "bottom-full mb-2",
            className
          )}
        >
          {content}
        </span>
      )}
    </span>
  )
}

export function InfoTooltip({ content, className }: { content: React.ReactNode; className?: string }) {
  return (
    <Tooltip content={content} className={className}>
      <HelpCircle className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
    </Tooltip>
  )
}
