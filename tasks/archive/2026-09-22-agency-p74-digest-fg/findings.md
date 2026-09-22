# Hallazgos

- `POST /api/digests/generate` llama a `_snapshot` con `expected_revision=None`, `require_enabled=False`. Un administrador puede generar sin política; un miembro recibe `policy_missing` si falta. La política es opt-in y sólo un administrador puede configurarla en Cliente → Resúmenes.
- El formulario individual ofrecía todos los clientes activos aunque no hubiera política para el miembro, y `getErrorMessage` serializaba `detail` como JSON visible.
- Tras consultar la política de un miembro, `GET /api/digests/policies/{id}` responde 403 si falta o si el responsable es otra persona. Se requiere mensaje que cubra ambas posibilidades sin revelar detalles ajenos.
- La segunda fase de `generate_locked_digest` revalida la revisión inicial tras el proveedor; así detecta cambios de política durante la generación.
- No había credenciales de producción fiables en el worktree. La ausencia de política FG se infiere del error reportado y del flujo, sin lectura directa.
