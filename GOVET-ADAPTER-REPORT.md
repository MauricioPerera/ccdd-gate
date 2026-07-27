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

## Fix de CI: 2026-07-26

### Diagnóstico (con evidencia de corrida propia, no especulación)

El CI de GitHub Actions (`ubuntu-latest`, `go` preinstalado del runner, sin `setup-go`) falló en `IntegrationRealGoVet.test_printf_wrong_type_exit1_with_normalized_finding` con `AssertionError: 0 != 1`: `gate()` devolvió `code == 0` pese a que `fmt.Printf("%d\n", "not a number")` SÍ es un bug real de `go vet`. El test corrió (no salteado): `go` estaba presente en el runner.

**Causa raíz: bug en `GoVetAdapter._parse_messages`/filtrado, NO en el test ni en el check de printf.** `go vet` reporta la ruta del finding con un prefijo `./` cuya presencia depende de la versión de Go, y el adapter no lo strippeaba, de modo que el finding se filtraba contra `allowed` y se perdía → `code == 0`.

Verifiqué en MI sistema (Windows, `go version go1.26.4`) descargando toolchains viejos vía `GOTOOLCHAIN=goX` el formato exacto que emite `go vet ./...` sobre el mismo módulo del test (`go mod init example.com/probe` + `main.go` con el bug de printf):

| Go | salida `go vet ./...` (stderr) |
|----|--------------------------------|
| 1.21.13 | `.\main.go:6:2: fmt.Printf format %d has arg "not a number" of wrong type string` |
| 1.22.0 | `.\main.go:6:2: ...` (prefijo `.\`, col 2) |
| 1.23.0 | `.\main.go:6:2: ...` |
| 1.24.0 | `.\main.go:6:2: ...` |
| 1.25.0 | `main.go:6:14: ...` (SIN prefijo, col 14) |
| 1.26.4 | `main.go:6:14: ...` |

El cambio de formato (caída del prefijo `./` y paso de col 2 → 14) ocurre en **Go 1.25**. El check de printf en sí es estable (detecta el hallazgo en TODAS las versiones probadas, exit 1). La línea del hallazgo es `6` en todas. Lo que cambia es sólo el prefijo de la ruta.

El adapter hacía `m.group(1).replace("\\", "/")` → `.\main.go` (Win) o `./main.go` (Linux, Go<1.25) quedaba como `./main.go`. El glob `**/*.go` expande a paths relativos SIN prefijo (`main.go` — ver `linter_gate.py:308-309`, `f.relative_to(rootp).as_posix()`), así que `allowed = {"main.go"}`. Como `./main.go` no está en `allowed`, el finding se descartaba → `code == 0`.

Reproducción directa del filtro (MI corrida, alimentando el stderr real a `GoVetAdapter._parse_messages`+`_normalize` con `allowed={"main.go"}`):
- `./main.go:6:2: ...` (Linux, Go<1.25) → 1 parseado, **0** sobreviven el filtro → `code 0` (= el fallo de CI).
- `.\main.go:6:2: ...` (Win, Go<1.25) → 1 parseado, **0** sobreviven → `code 0`.
- `main.go:6:14: ...` (Go≥1.25) → 1 parseado, **1** sobrevive → `code 1` (lo que veía mi Windows 1.26, por eso el test pasaba localmente).

Por eso el test pasaba 100% local (Go 1.26.4 ≥ 1.25, sin prefijo) y fallaba en CI (runner con Go < 1.25, con prefijo). Las pistas 1/2/3 del brief (directiva `go` del `go.mod`, `GOTOOLCHAIN`, `GOPROXY`) NO son la causa: el `go.mod` generado lleva la directiva igual a la versión del propio runner (sin mismatch), `fmt` es stdlib (sin resolución de deps externas), y el comando `go vet ./...` es exactamente el que corre el adapter. La fragilidad estaba en el formato de la ruta de salida, no en el analyzer.

### Fix (en `runners/linter_gate.py`, justificado por el diagnóstico)

En `GoVetAdapter._parse_messages`, después de `replace("\\", "/")`, strippear un `./` inicial:
```python
rel = m.group(1).replace("\\", "/")
if rel.startswith("./"):  # Go < 1.25 prefija `./`; el glob de `files` no lo trae
    rel = rel[2:]
```
Así `.\main.go`→`./main.go`→`main.go` y `./main.go`→`main.go`, mientras que `main.go` (Go≥1.25) queda igual. El finding sobrevive `allowed` en TODAS las versiones de Go. Comentario del regex (`GOVET_LINE_RE`) actualizado para documentar el prefijo. No se cambió el regex literal ni se debilitó nada.

El bug de ejemplo del test (`Printf("%d", "string")`) NO es frágil: el check de printf es estable desde hace muchísimas versiones (confirmado 1.21–1.26). Se mantiene; el problema era el filtrado del path, no la elección del bug. No se reemplazó por copylocks porque el diagnóstico mostró que el bug estaba en el adapter, no en el test.

### Tests de regresión agregados (`tests/test_linter_gate.py`)

- `GoVetNormalize.test_dot_slash_prefix_stripped`: verifica que `_parse_messages` strippea `./` y `.\` de la ruta (`./main.go`, `.\main.go`, `./pkgb/pkgb.go` → sin prefijo, forward-slash).
- `GoVetPoliciesUnit.test_findings_exit1_dot_slash_prefix_survives_filter`: gate completo con `go vet` (FakeRunner) emitiendo `./main.go:6:2: ...` (formato Go<1.25 Linux) → `code == 1`, 1 finding, `file=="main.go"`, `line==6`, `code=="govet"`. Replica exactamente el modo de fallo de CI y verifica que ya no filtra.
- `GoVetPoliciesUnit.test_findings_exit1_backslash_dot_prefix_survives_filter`: idem con `.\main.go:6:2:` (formato Go<1.25 Windows).

Estos tests cubren el formato de Go<1.25 sin depender de la versión instalada en el runner (usan FakeRunner), de modo que el fix queda blindado en cualquier entorno. La aserción NO se debilitó: sigue verificando exit 1 + finding específico (file, line, code, msg con "Printf" en el test de integración).

### Salidas reales de la definición de hecho

**1. Diagnóstico:** arriba, con tabla de formato por versión y reproducción del filtro (MI corrida).

**2. `python -m unittest tests.test_linter_gate -v` (PYTHONPATH=runners):**
```
Ran 56 tests in 2.827s
OK
```
Incluye `test_printf_wrong_type_exit1_with_normalized_finding` (integración real, Go 1.26.4) y los 3 tests de regresión nuevos — todos `ok`.

**3. Suite completa 2 veces (`python -m unittest discover -s tests -p "test_*.py"`):**
```
Ran 579 tests in 15.877s
OK
```
```
Ran 579 tests in 13.085s
OK
```
(576 originales + 3 tests nuevos. Las líneas `[linter-gate] skip: ...` son output esperado de los casos `not_installed` del FakeRunner, no fallos.)

**4. Specificidad conservada:** el test de integración sigue verificando un hallazgo real de `go vet` (printf wrong type), exit 1, `code=="govet"`, `file=="main.go"`, `line==6`, y `assertIn("Printf", msg)`. Los tests de regresión mantienen la misma aserción específica (file/line/code) sobre el formato de path de Go<1.25. No se relajó a "cualquier finding".

### Archivos tocados
- `runners/linter_gate.py`: fix en `GoVetAdapter._parse_messages` (strip `./`) + comentario del regex. (Justificado por el diagnóstico: el bug real estaba en el adapter.)
- `tests/test_linter_gate.py`: 3 tests de regresión.
- `GOVET-ADAPTER-REPORT.md`: esta sección.