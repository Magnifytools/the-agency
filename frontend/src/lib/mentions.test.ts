import { describe, expect, it } from "vitest"
import type { User } from "@/lib/types"
import { activeMention, insertMention, mentionCandidates, mentionName, mentionedIds, splitMentions } from "./mentions"

const user = (id: number, full_name: string, short_name: string | null = null, is_active = true) =>
  ({ id, full_name, short_name, is_active }) as User

describe("menciones", () => {
  it("usa el nombre corto o la primera palabra, y sólo personas activas", () => {
    expect(mentionName(user(1, "David Carrasco", "David"))).toBe("David")
    expect(mentionName(user(2, "Ignacio Pérez"))).toBe("Ignacio")
    expect(mentionCandidates([user(1, "David Carrasco"), user(3, "Antigua", null, false)]).map((c) => c.id)).toEqual([1])
  })

  it("detecta la @ que se está escribiendo, no un email", () => {
    expect(activeMention("Hola @Na", 8)).toEqual({ start: 5, query: "Na" })
    expect(activeMention("@", 1)).toEqual({ start: 0, query: "" })
    expect(activeMention("escribe a nacho@magnify.ing", 27)).toBeNull()
    expect(activeMention("Hola @Na y más", 14)).toBeNull()
  })

  it("pone la mención con un espacio detrás y deja el cursor tras ella", () => {
    expect(insertMention("Hola @Na que tal", 5, 8, "Nacho")).toEqual({ text: "Hola @Nacho que tal", caret: 12 })
  })

  it("sólo avisa a quien sigue mencionado en el texto", () => {
    const picked = [{ id: 2, name: "Nacho", fullName: "Nacho" }, { id: 1, name: "David", fullName: "David" }]
    expect(mentionedIds("@Nacho mira esto", picked)).toEqual([2])
    expect(mentionedIds("@Nachoo mira esto", picked)).toEqual([])
    expect(mentionedIds("@Nacho y @David, @Nacho", picked)).toEqual([2, 1])
  })

  it("marca las @ de personas conocidas al pintar el comentario", () => {
    expect(splitMentions("Ok @nacho, y @nadie", ["Nacho"])).toEqual([
      { text: "Ok ", mention: false }, { text: "@nacho", mention: true }, { text: ", y @nadie", mention: false },
    ])
  })
})
