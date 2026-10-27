import { describe, expect, it } from "vitest"
import { DEFAULT_LENGTH, generatePassword, MAX_LENGTH, MIN_LENGTH } from "./password-generator"

describe("generatePassword", () => {
  it("has the requested length and one character of each kind", () => {
    for (let i = 0; i < 50; i++) {
      const value = generatePassword()
      expect(value).toHaveLength(DEFAULT_LENGTH)
      expect(value).toMatch(/[a-z]/)
      expect(value).toMatch(/[A-Z]/)
      expect(value).toMatch(/[2-9]/)
      expect(value).toMatch(/[!#$%&*+\-=?@^_]/)
    }
  })

  it("leaves out symbols and look-alike characters when asked", () => {
    const value = generatePassword({ length: 40, symbols: false })
    expect(value).toMatch(/^[A-Za-z2-9]{40}$/)
    expect(value).not.toMatch(/[lIO01]/)
  })

  it("keeps the length within bounds", () => {
    expect(generatePassword({ length: 3 })).toHaveLength(MIN_LENGTH)
    expect(generatePassword({ length: 500 })).toHaveLength(MAX_LENGTH)
  })

  it("does not repeat itself", () => {
    const values = new Set(Array.from({ length: 200 }, () => generatePassword()))
    expect(values.size).toBe(200)
  })

  it("discards biased random values instead of using them", () => {
    // 0xFFFFFFFF cae por encima del límite para cualquier tamaño de alfabeto: se descarta.
    let calls = 0
    const random = (buffer: Uint32Array) => {
      buffer[0] = calls++ % 2 === 0 ? 0xffffffff : 7
      return buffer
    }
    expect(generatePassword({ length: 12 }, random)).toHaveLength(12)
    expect(calls).toBeGreaterThan(12 * 2 - 1)
  })
})
