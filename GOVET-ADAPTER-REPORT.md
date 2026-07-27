# GOVET-ADAPTER-REPORT

## Resumen

Implementé `GoVetAdapter` en `runners/linter_gate.py` que envuelve `go vet` (toolchain de Go, ya presente en el sistema) como check opt-in del gate. Replica el diseño de `ClippyAdapter` (linter de módulo/paquete completo, no por-archivo): `files` se usa solo para (a) skip si el glob está vacío y (b) post-filtrar findings a esos paths. Registrado en `ADAPTERS` con clave `"govet"` (binario `go`, `name="go"`).

Cambios:
- `GoVetAdapter` con `installed_version` (`go version` → 3er token, ej. `go1.26.4`), `collect` (`go vet ./...` por defecto o `args` si vienen; findings desde **stderr**; exit 0 limpio · 1 findings · otro → `ToolError`), `_parse_messages` (regex `^(.+?):(\d+):(\d+):\s*(.+)$`, ignora líneas que no matchean, normaliza backslash → forward-slash), `_normalize` (filtra a `allowed`, ordena por `(file, line, code)`, `code="govet"` constante).
- `ADAPTERS` ahora incluye `"govet": GoVetAdapter()`.
- `import re` agregado; `GOVET_LINE_RE` a nivel módulo.
- Docstring del módulo y comentario del registro actualizados para incluir `govet`.

Tests en `tests/test_linter_gate.py` (mismo patrón que Clippy): `GoVetNormalize`, `GoVetPoliciesUnit` (con `GoVetFakeRunner`), `IntegrationRealGoVet` (real, `@skipUnless` si `go` no está, módulo vía `go mod init example.com/probe`).

Solo se tocaron `runners/linter_gate.py` y `tests/test_linter_gate.py`.

## Salidas reales de la definición de hecho

### Punto 1 — `python -m unittest tests.test_linter_gate -v` (PYTHONPATH=runners)

```
Ran 53 tests in 2.666s

OK
```

(Todos los tests ruff + clippy + govet en verde. Las líneas `[linter-gate] skip: ...` corresponden a los casos `not_installed=True` del FakeRunner, que son los esperados.)

### Punto 2 — Corrida manual: `python runners/linter_gate.py linters.yaml .`

Mini-proyecto Go en tempdir con `fmt.Printf("%d\n", "not a number")` (bug real de `go vet`), YAML:
```yaml
- tool: govet
  version: "go1.26.4"
  files: "**/*.go"
```

Salida JSON real (exit=1):
```json
{
  "ok": false,
  "results": [
    {
      "tool": "govet",
      "version": "go1.26.4",
      "findings": [
        {
          "file": "main.go",
          "line": 6,
          "code": "govet",
          "msg": "fmt.Printf format %d has arg \"not a number\" of wrong type string"
        }
      ]
    }
  ]
}
```

### Punto 3 — Suite completa del repo

```
Ran 576 tests in 14.235s

OK
```

(Las líneas `sin backend de métricas para m.cobol ...` y los `skip: ...` son output esperado de tests existentes — no fallos.)

## Trade-offs / observaciones

- **Formato verificado**: confirmé corriendo `go vet ./...` en este sistema que los hallazgos van a **stderr** (no stdout), una línea por hallazgo `<ruta-relativa>:<linea>:<col>: <msg>`, exit 0 limpio / exit 1 con findings. En Windows la ruta relativa viene con backslash (`pkgb\pkgb.go`) — normalizada a forward-slash. Coincide con la descripción del objetivo; sin desviaciones.
- **`code` constante**: `go vet` no expone códigos de regla por hallazgo; se usa `"govet"` fijo, como pide el objetivo.
- **Versión**: `go vet` no tiene `--version`; se usa `go version` y se parsea el 3er token (`go1.26.4` con prefijo `go`), comparable 1:1 contra el pin YAML.
- **Edge case de error de compilación (fuera de scope de tests)**: si el código no compila, `go vet` emite a stderr líneas `# example.com/probe` / `# [example.com/probe]` (ignoradas correctamente por el regex) **y** una línea tipo `vet.exe: .\main.go:4:2: undefined: foo`. Esta última sí matchea el regex `.+?` y produciría un finding con `file` espurio (`vet.exe: .\main.go`). No está cubierto por los tests (el objetivo solo pide bug-vet y limpio) y se conserva el regex exacto pedido. En la práctica un error de compilación igual resulta exit 1 (algo anda mal), que es lo deseable; el `file` del finding sería ruidoso pero no silent. Si se quisiera silenciarlo, habría que restringir el grupo de path a `[^:]+?` (sin dos puntos), pero eso desviaría el regex literalmente pedido — se deja como está.
- **`_normalize` conserva parámetro `root`** por simetría con `ClippyAdapter` (allí también es efectivamente unused: los paths de cargo/vet ya son relativos al cwd).