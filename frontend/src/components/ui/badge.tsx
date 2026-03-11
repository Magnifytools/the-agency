import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default: "bg-brand/10 text-brand",
        secondary: "bg-secondary text-secondary-foreground",
        destructive: "bg-red-500 text-white",
        outline: "bg-slate-500/80 text-white",
        success: "bg-green-500 text-white",
        warning: "bg-orange-500 text-white",
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
    destructive: "bg-white",
    outline: "bg-white",
    success: "bg-white",
    warning: "bg-white",
  }

  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot && <span className={cn("inline-block h-1.5 w-1.5 rounded-full", dotColors[variant || "default"])} />}
      {props.children}
    </div>
  )
}

export { Badge }
