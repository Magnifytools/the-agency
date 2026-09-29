# P40 — ACL de procedencia en respuestas de digest (checkout civil)

1. Ejecutar como baseline la regresión PostgreSQL existente de ACL/procedencia.
2. Extenderla para demostrar que un responsable sin los módulos fuente recibe claves privadas en `content.source_keys`, mientras el creador autorizado conserva su clave.
3. Proyectar las claves de procedencia de la respuesta contra el catálogo ya filtrado por ACL, sin modificar la entidad persistida ni el texto del informe.
4. Repetir la prueba focal y el subconjunto de digests relacionado; revisar el diff y crear un commit local si todo pasa.
