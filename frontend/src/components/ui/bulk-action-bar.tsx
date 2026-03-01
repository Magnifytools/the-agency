interface Props {
  selectedCount: number
  onClear: () => void
  children: React.ReactNode
}

export function BulkActionBar({ selectedCount, onClear, children }: Props) {
  if (selectedCount === 0) return null

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 bg-card border border-brand/30 rounded-xl shadow-2xl px-5 py-3 flex items-center gap-4 animate-in slide-in-from-bottom-4 duration-200">
      <span className="text-sm font-semibold text-brand">{selectedCount} seleccionados</span>
      <div className="h-5 w-px bg-border" />
      <div className="flex items-center gap-2">
        {children}
      </div>
      <button
        onClick={onClear}
        className="text-xs text-muted-foreground hover:text-foreground ml-2"
      >
        Limpiar
      </button>
    </div>
  )
}
