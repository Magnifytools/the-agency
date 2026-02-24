import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import { AxiosError } from "axios"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

interface ApiErrorResponse {
  detail: string | { msg: string; type: string }[]
}

/**
 * Extract a human-readable error message from an API error.
 * Handles FastAPI's error formats:
 * - { detail: "string" } for HTTPException
 * - { detail: [{ msg, type }] } for validation errors (422)
 */
export function getErrorMessage(error: unknown, fallback = "Error inesperado"): string {
  if (error instanceof AxiosError && error.response?.data) {
    const data = error.response.data as ApiErrorResponse
    if (typeof data.detail === "string") {
      return data.detail
    }
    if (Array.isArray(data.detail)) {
      return data.detail.map((d) => d.msg).join(", ")
    }
  }
  if (error instanceof Error) {
    return error.message
  }
  return fallback
}
