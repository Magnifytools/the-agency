import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default: "bg-brand/10 text-blue-400",
        secondary: "bg-secondary text-secondary-foreground",
        destructive: "bg-destructive/10 text-red-400",
        outline: "border border-border text-foreground",
        success: "bg-green-500/10 text-green-400",
        warning: "bg-yellow-500/10 text-yellow-400",
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
    default: "bg-blue-400",
    secondary: "bg-muted-foreground",
    destructive: "bg-red-400",
    outline: "bg-foreground",
    success: "bg-green-400",
    warning: "bg-yellow-400",
  }

  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot && <span className={cn("inline-block h-1.5 w-1.5 rounded-full", dotColors[variant || "default"])} />}
      {props.children}
    </div>
  )
}

export { Badge, badgeVariants }
