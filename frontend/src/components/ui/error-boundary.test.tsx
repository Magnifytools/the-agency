import { lazy, Suspense } from "react"
import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ErrorBoundary, isLazyModuleLoadError } from "./error-boundary"

const chunkFailure = "Failed to fetch dynamically imported module"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("ErrorBoundary", () => {
  it.each([
    "Failed to fetch dynamically imported module",
    "Error loading dynamically imported module",
    "Importing a module script failed.",
    "ChunkLoadError: Loading chunk 42 failed.",
  ])("recognizes lazy-module load errors from browsers and bundlers: %s", (message) => {
    expect(isLazyModuleLoadError(new Error(message))).toBe(true)
  })

  it("does not mistake an ordinary render error for a stale module", () => {
    expect(isLazyModuleLoadError(new Error("Cannot read properties of undefined"))).toBe(false)
    expect(isLazyModuleLoadError(null)).toBe(false)
  })

  it("retries an ordinary render error without reloading the page", () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined)
    let shouldThrow = true
    const BrokenView = () => {
      if (shouldThrow) throw new Error("ordinary render failure")
      return <p>Recovered</p>
    }

    render(<div onClick={() => { shouldThrow = false }}><ErrorBoundary><BrokenView /></ErrorBoundary></div>)

    const reload = vi.fn()
    vi.stubGlobal("window", { location: { reload } })
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))

    expect(screen.getByText("Recovered")).toBeInTheDocument()
    expect(reload).not.toHaveBeenCalled()
    log.mockRestore()
  })

  it("reloads after a lazy route module cannot be fetched", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined)
    const UnavailableRoute = lazy(() => Promise.reject(new Error(chunkFailure)))

    render(<ErrorBoundary><Suspense fallback={<p>Loading</p>}><UnavailableRoute /></Suspense></ErrorBoundary>)

    const reloadButton = await screen.findByRole("button", { name: "Recargar página" })
    const reload = vi.fn()
    vi.stubGlobal("window", { location: { reload } })
    fireEvent.click(reloadButton)

    expect(reload).toHaveBeenCalledOnce()
    log.mockRestore()
  })
})
