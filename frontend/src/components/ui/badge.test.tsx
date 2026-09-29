import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { Badge } from "./badge"

describe("Badge", () => {
  it.each([
    ["destructive", "bg-red-950", "text-red-200"],
    ["success", "bg-green-950", "text-green-200"],
    ["warning", "bg-amber-950", "text-amber-200"],
    ["outline", "bg-slate-800", "text-slate-100"],
  ] as const)("uses the accessible %s palette", (variant, background, foreground) => {
    render(<Badge variant={variant}>{variant}</Badge>)
    expect(screen.getByText(variant)).toHaveClass(background, foreground)
  })
})
