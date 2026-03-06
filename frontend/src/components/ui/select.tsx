import * as React from "react"
import { cn } from "@/lib/utils"

const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, "aria-invalid": ariaInvalid, ...props }, ref) => (
    <select
      aria-invalid={ariaInvalid}
      className={cn(
        "flex h-10 w-full rounded-[10px] border border-border bg-background px-3 py-2 pr-8 text-sm text-foreground transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive",
        className
      )}
      ref={ref}
      {...props}
    >
      {children}
    </select>
  )
)
Select.displayName = "Select"

export { Select }
