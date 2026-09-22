# Progreso

- Implementados mensaje backend específico y lectura de `detail.message` en frontend.
- El formulario verifica asignación del miembro, explica el requisito y ofrece reconsulta después de configurar.
- Verificación con dependencias fijadas: `npm ci`, build completo y 17/17 pruebas UI focales aprobadas.
- PostgreSQL efímero aislado: 15/15 pruebas P27 (incluidos alta de política y cambio de revisión durante el proveedor) y 16/16 pruebas de digest y límites de política aprobadas.
- `python3.12 -m py_compile` y `git diff --check` correctos. No se accedió a datos productivos.
- Ajuste posterior: la UI exige `responsible_can_prepare` y explica cuenta/permiso inválidos. La política desactivada sigue permitiendo una versión individual, conforme al backend. Las dos regresiones nuevas pasaron por separado tras agotar tiempo bajo carga extrema del host en una ejecución conjunta; build repetido pendiente.
