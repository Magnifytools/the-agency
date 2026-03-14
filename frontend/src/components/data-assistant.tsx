import { useState, useRef, useEffect } from "react"
import { useMutation } from "@tanstack/react-query"
import { assistantApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import { Bot, Send, X, Loader2 } from "lucide-react"

interface Message {
  role: "user" | "assistant"
  content: string
}

const SUGGESTIONS = [
  "¿Quién tiene más carga esta semana?",
  "¿Cuántas horas se registraron este mes?",
  "¿Qué clientes no tienen horas esta semana?",
  "¿Cuántas tareas vencidas hay?",
]

export function DataAssistant() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<Message[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  const isAdmin = user?.role === "admin"

  const askMutation = useMutation({
    mutationFn: (question: string) => assistantApi.ask(question),
    onSuccess: (data) => {
      setMessages((prev) => [...prev, { role: "assistant", content: data.answer }])
    },
    onError: () => {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Error al procesar la pregunta. Inténtalo de nuevo." },
      ])
    },
  })

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  if (!isAdmin) return null

  const handleSend = (text?: string) => {
    const q = (text || input).trim()
    if (!q || askMutation.isPending) return
    setMessages((prev) => [...prev, { role: "user", content: q }])
    setInput("")
    askMutation.mutate(q)
  }

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-50 h-12 w-12 rounded-full bg-brand text-white shadow-lg flex items-center justify-center hover:bg-brand/90 transition-colors"
          title="Asistente de datos"
        >
          <Bot className="h-6 w-6" />
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-6 right-6 z-50 w-[380px] h-[520px] bg-background border rounded-xl shadow-2xl flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-brand" />
              <div>
                <p className="text-sm font-semibold">Asistente de datos</p>
                <p className="text-[10px] text-muted-foreground">Pregunta sobre tu agencia</p>
              </div>
            </div>
            <button onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  Pregúntame lo que quieras sobre los datos. Voy al grano.
                </p>
                <p className="text-xs font-semibold text-muted-foreground uppercase">Sugerencias:</p>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => handleSend(s)}
                    className="block w-full text-left text-sm px-3 py-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`text-sm whitespace-pre-wrap ${
                  msg.role === "user"
                    ? "bg-brand/10 text-brand-foreground ml-8 px-3 py-2 rounded-lg"
                    : "bg-muted px-3 py-2 rounded-lg mr-4"
                }`}
              >
                {msg.content}
              </div>
            ))}

            {askMutation.isPending && (
              <div className="flex items-center gap-2 text-muted-foreground text-sm px-3 py-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Pensando...
              </div>
            )}
          </div>

          {/* Input */}
          <div className="border-t p-3 flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="Escribí tu pregunta..."
              className="flex-1 bg-muted rounded-lg px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-brand"
              disabled={askMutation.isPending}
            />
            <button
              onClick={() => handleSend()}
              disabled={!input.trim() || askMutation.isPending}
              className="h-9 w-9 rounded-lg bg-brand text-white flex items-center justify-center disabled:opacity-50 hover:bg-brand/90"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </>
  )
}
