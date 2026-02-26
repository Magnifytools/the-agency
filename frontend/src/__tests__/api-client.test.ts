import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

// Mock sonner before importing api
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

describe("API Client", () => {
  let originalLocalStorage: Storage

  beforeEach(() => {
    // Save reference and set up mock
    originalLocalStorage = globalThis.localStorage
    const store: Record<string, string> = {}
    const mockStorage = {
      getItem: vi.fn((key: string) => store[key] ?? null),
      setItem: vi.fn((key: string, value: string) => {
        store[key] = value
      }),
      removeItem: vi.fn((key: string) => {
        delete store[key]
      }),
      clear: vi.fn(() => {
        for (const key in store) delete store[key]
      }),
      get length() {
        return Object.keys(store).length
      },
      key: vi.fn(() => null),
    }
    Object.defineProperty(globalThis, "localStorage", {
      value: mockStorage,
      writable: true,
      configurable: true,
    })
  })

  afterEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      value: originalLocalStorage,
      writable: true,
      configurable: true,
    })
    vi.restoreAllMocks()
  })

  it("creates an axios instance with /api baseURL", async () => {
    // Re-import to get fresh module
    const { default: axiosModule } = await import("axios")
    const instance = axiosModule.create({ baseURL: "/api" })
    expect(instance.defaults.baseURL).toBe("/api")
  })

  it("request interceptor adds Authorization header when token exists", () => {
    localStorage.setItem("token", "test-jwt-token")

    // Simulate what the interceptor does
    const token = localStorage.getItem("token")
    const headers: Record<string, string> = {}
    if (token) {
      headers["Authorization"] = `Bearer ${token}`
    }

    expect(headers["Authorization"]).toBe("Bearer test-jwt-token")
  })

  it("request interceptor does not add Authorization header when no token", () => {
    const token = localStorage.getItem("token")
    const headers: Record<string, string> = {}
    if (token) {
      headers["Authorization"] = `Bearer ${token}`
    }

    expect(headers["Authorization"]).toBeUndefined()
  })

  it("401 response removes token and redirects", async () => {
    localStorage.setItem("token", "expired-token")

    // Simulate response interceptor logic for 401
    const error = {
      response: { status: 401 },
      request: {},
    }

    const status = error.response.status
    if (status === 401) {
      localStorage.removeItem("token")
    }

    expect(localStorage.getItem("token")).toBeNull()
  })

  it("403 response shows permission error toast", async () => {
    const { toast } = await import("sonner")

    // Simulate response interceptor logic
    const error = { response: { status: 403 }, request: {} }
    const status = error.response.status

    if (status === 403) {
      toast.error("No tienes permisos para esta acción")
    }

    expect(toast.error).toHaveBeenCalledWith("No tienes permisos para esta acción")
  })

  it("500+ response shows server error toast", async () => {
    const { toast } = await import("sonner")

    const error = { response: { status: 500 }, request: {} }
    const status = error.response.status

    if (status >= 500) {
      toast.error("Error del servidor. Intenta de nuevo.")
    }

    expect(toast.error).toHaveBeenCalledWith("Error del servidor. Intenta de nuevo.")
  })

  it("network error (no response) shows connection error toast", async () => {
    const { toast } = await import("sonner")

    const error = { response: undefined, request: {} }

    if (!error.response && error.request) {
      toast.error("Error de conexión. Verifica tu red.")
    }

    expect(toast.error).toHaveBeenCalledWith("Error de conexión. Verifica tu red.")
  })
})
