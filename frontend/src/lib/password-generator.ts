/**
 * Contraseñas aleatorias para Accesos. Sólo en el navegador y con
 * `crypto.getRandomValues` (nunca Math.random): la contraseña no pasa por el
 * servidor hasta que se guarda, cifrada, como cualquier otra.
 */

const LOWER = "abcdefghijkmnopqrstuvwxyz" // sin l
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ" // sin I ni O
const DIGITS = "23456789" // sin 0 ni 1
// Los que aceptan casi todos los formularios (sin comillas, espacios ni barras).
const SYMBOLS = "!#$%&*+-=?@^_"

export const MIN_LENGTH = 12
export const MAX_LENGTH = 64
export const DEFAULT_LENGTH = 20

/** Índice uniforme en [0, max): descarta lo que sesgaría el módulo. */
function randomIndex(max: number, random: (buffer: Uint32Array) => Uint32Array): number {
  const limit = Math.floor(0x100000000 / max) * max
  const buffer = new Uint32Array(1)
  for (;;) {
    random(buffer)
    if (buffer[0] < limit) return buffer[0] % max
  }
}

export function generatePassword(
  { length = DEFAULT_LENGTH, symbols = true }: { length?: number; symbols?: boolean } = {},
  random: (buffer: Uint32Array) => Uint32Array = (buffer) => crypto.getRandomValues(buffer),
): string {
  const size = Math.min(MAX_LENGTH, Math.max(MIN_LENGTH, Math.round(length)))
  const groups = symbols ? [LOWER, UPPER, DIGITS, SYMBOLS] : [LOWER, UPPER, DIGITS]
  const all = groups.join("")
  // Uno de cada grupo (muchas webs lo exigen) y el resto de todos.
  const chars = groups.map((group) => group[randomIndex(group.length, random)])
  while (chars.length < size) chars.push(all[randomIndex(all.length, random)])
  // Fisher-Yates para que los obligatorios no queden siempre al principio.
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomIndex(i + 1, random)
    ;[chars[i], chars[j]] = [chars[j], chars[i]]
  }
  return chars.join("")
}
