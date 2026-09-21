import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default: "bg-brand/10 text-brand",
        secondary: "bg-secondary text-secondary-foreground",
        destructive: "border border-red-800 bg-red-950 text-red-200",
        outline: "border border-slate-600 bg-slate-800 text-slate-100",
        success: "border border-green-800 bg-green-950 text-green-200",
        warning: "border border-amber-800 bg-amber-950 text-amber-200",
      },
    },
    defaultVariants: { variant: "default" },
  }
)

interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {
  dot?: boolean
}

function Badge({ className, variant, dot = true, ...props }: BadgeProps) {
  const dotColors: Record<string, string> = {
    default: "bg-brand",
    secondary: "bg-muted-foreground",
    destructive: "bg-red-300",
    outline: "bg-slate-300",
    success: "bg-green-300",
    warning: "bg-amber-300",
  }

  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot && <span className={cn("inline-block h-1.5 w-1.5 rounded-full", dotColors[variant || "default"])} />}
      {props.children}
    </div>
  )
}

export { Badge }
