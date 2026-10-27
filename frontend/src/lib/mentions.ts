import type { User } from "@/lib/types"

export interface MentionCandidate {
  id: number
  name: string
  fullName: string
}

/** Cómo se escribe a alguien tras la @: su nombre corto o la primera palabra del nombre. */
export function mentionName(user: Pick<User, "short_name" | "full_name">) {
  return (user.short_name?.trim() || user.full_name.trim().split(/\s+/)[0] || "").replace(/\s+/g, "")
}

export function mentionCandidates(users: User[]): MentionCandidate[] {
  return users
    .filter((user) => user.is_active)
    .map((user) => ({ id: user.id, name: mentionName(user), fullName: user.full_name }))
    .filter((candidate) => candidate.name)
}

/** La @ que se está escribiendo justo antes del cursor, si la hay. */
export function activeMention(text: string, caret: number): { start: number; query: string } | null {
  const match = text.slice(0, caret).match(/(^|\s)@([\p{L}\p{N}._-]*)$/u)
  if (!match) return null
  return { start: caret - match[2].length - 1, query: match[2] }
}

export function insertMention(text: string, start: number, caret: number, name: string) {
  const before = `${text.slice(0, start)}@${name} `
  const after = text.slice(caret).replace(/^\s+/, "")
  return { text: before + after, caret: before.length }
}

function hasToken(text: string, name: string) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  return new RegExp(`(^|\\s)@${escaped}(?![\\p{L}\\p{N}_-])`, "u").test(text)
}

/** Ids elegidos cuya @ sigue en el texto (si se borró la mención, no se avisa). */
export function mentionedIds(text: string, picked: MentionCandidate[]) {
  return [...new Set(picked.filter((candidate) => hasToken(text, candidate.name)).map((candidate) => candidate.id))]
}

/** Trozos de un comentario con las @ de personas conocidas marcadas. */
export function splitMentions(text: string, names: string[]): Array<{ text: string; mention: boolean }> {
  const known = new Set(names.map((name) => name.toLocaleLowerCase("es")))
  const parts: Array<{ text: string; mention: boolean }> = []
  let last = 0
  for (const match of text.matchAll(/(^|\s)(@[\p{L}\p{N}._-]+)/gu)) {
    const token = match[2]
    if (!known.has(token.slice(1).toLocaleLowerCase("es"))) continue
    const start = (match.index ?? 0) + match[1].length
    if (start > last) parts.push({ text: text.slice(last, start), mention: false })
    parts.push({ text: token, mention: true })
    last = start + token.length
  }
  if (last < text.length) parts.push({ text: text.slice(last), mention: false })
  return parts
}
