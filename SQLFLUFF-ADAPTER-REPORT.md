# SQLFLUFF-ADAPTER-REPORT

## Resumen

Implementé `SqlfluffAdapter` en `runners/linter_gate.py` y sus tests en `tests/test_linter_gate.py`. Toqué SOLO esos dos archivos.

`sqlfluff` es **por-archivo como ruff** (acepta una lista de archivos como args posicionales al final, lintea varios en una invocación), NO de módulo completo como clippy/govet. Por eso replica el diseño de `RuffAdapter`:

- `installed_version`: `sqlfluff --version` → `"sqlfluff, version 4.2.2"` → último token (`out.strip().split()[-1]`) → `"4.2.2"`. NO usa `parts[1]` como ruff (acá hay 3 tokens con una coma pegada al primero).
- `collect`: `cmd = ["sqlfluff", "lint"] + args + files + ["--format", "json"]`. exit 0 limpio · 1 findings · otro → `ToolError` (entorno inválido).
- `_normalize`: itera la lista externa (un item por archivo, campo `filepath`) y por cada archivo itera su lista interna `violations`, extrayendo `start_line_no` → `line`, `code` → `code` (alfanumérico real tipo `LT09`, NO constante), `description` → `msg`. Normaliza `filepath` relativizando a `root` con fallback `Path(fn).as_posix()` (forward-slash) si no está bajo root — misma defensividad que `RuffAdapter`. Archivos con `violations: []` no generan findings. Output ordenado por `(file, line, code)`.

El dialecto SQL (`--dialect postgres`) NO se hardcodea: se declara vía `args` en el `linters.yaml`. Registrado en `ADAPTERS` con clave `"sqlfluff"` (nombre real de la tool), `default_files = "**/*.sql"`. Actualizado el docstring del módulo y el comentario del registro para listar `sqlfluff`.

Tests (estilo Ruff, prefijo `Sqlfluff`): `SqlfluffNormalize`, `SqlfluffPoliciesUnit` (con `SqlfluffFakeRunner` inyectable), `IntegrationRealSqlfluff` (real, `@skipUnless` si no hay sqlfluff). Pin = versión instalada (mismo patrón que clippy/govet, no como ruff que pinea un example fijo).

## Definición de hecho — salida real

### 1. `python -m unittest tests.test_linter_gate -v` (PYTHONPATH=runners)

```
test_clean_exit0 (tests.test_linter_gate.IntegrationRealSqlfluff.test_clean_exit0) ... ok
test_style_violation_exit1_with_normalized_finding (tests.test_linter_gate.IntegrationRealSqlfluff.test_style_violation_exit1_with_normalized_finding) ... ok
test_version_mismatch_real_exit2 (tests.test_linter_gate.IntegrationRealSqlfluff.test_version_mismatch_real_exit2) ... ok
test_normalize_basic_and_sorted (tests.test_linter_gate.SqlfluffNormalize.test_normalize_basic_and_sorted) ... ok
test_normalize_empty (tests.test_linter_gate.SqlfluffNormalize.test_normalize_empty) ... ok
test_normalize_empty_violations_no_findings (tests.test_linter_gate.SqlfluffNormalize.test_normalize_empty_violations_no_findings) ... ok
test_normalize_outside_root_falls_back (tests.test_linter_gate.SqlfluffNormalize.test_normalize_outside_root_falls_back) ... ok
test_normalize_uses_forward_slashes (tests.test_linter_gate.SqlfluffNormalize.test_normalize_uses_forward_slashes) ... ok
test_ausente_not_required_skip_exit0 (tests.test_linter_gate.SqlfluffPoliciesUnit.test_ausente_not_required_skip_exit0) ... ok
test_ausente_required_exit2 (tests.test_linter_gate.SqlfluffPoliciesUnit.test_ausente_required_exit2) ... ok
test_clean_exit0 (tests.test_linter_gate.SqlfluffPoliciesUnit.test_clean_exit0) ... ok
test_default_files_is_sql_glob (tests.test_linter_gate.SqlfluffPoliciesUnit.test_default_files_is_sql_glob) ... ok
test_findings_exit1 (tests.test_linter_gate.SqlfluffPoliciesUnit.test_findings_exit1) ... ok
test_glob_empty_clean_exit0_never_invokes_lint (tests.test_linter_gate.SqlfluffPoliciesUnit.test_glob_empty_clean_exit0_never_invokes_lint) ... ok
test_tool_crash_exit2 (tests.test_linter_gate.SqlfluffPoliciesUnit.test_tool_crash_exit2) ... ok
test_uses_args_and_files_when_provided (tests.test_linter_gate.SqlfluffPoliciesUnit.test_uses_args_and_files_when_provided) ... ok
test_version_mismatch_exit2 (tests.test_linter_gate.SqlfluffPoliciesUnit.test_version_mismatch_exit2) ... ok
...
----------------------------------------------------------------------
Ran 73 tests in 5.687s

OK
```

Los 73 tests del módulo en verde: ruff + clippy + govet existentes + los nuevos de `SqlfluffAdapter`.

### 2. Corrida manual del gate sobre mini-proyecto real

`/tmp/sqlf_manual/linters.yaml`:
```yaml
- tool: sqlfluff
  version: "4.2.2"
  args: ["--dialect", "postgres"]
  files: "**/*.sql"
```
`bad.sql`: `select id,name from users where id=1` · `clean.sql`: SELECT multilínea bien formateado.

`PYTHONPATH=runners python runners/linter_gate.py /tmp/sqlf_manual/linters.yaml /tmp/sqlf_manual` → **EXIT=1**:
```json
{
  "ok": false,
  "results": [
    {
      "tool": "sqlfluff",
      "version": "4.2.2",
      "findings": [
        {"file": "bad.sql", "line": 1, "code": "LT01", "msg": "Expected single whitespace between comma ',' and naked identifier."},
        {"file": "bad.sql", "line": 1, "code": "LT01", "msg": "Expected single whitespace between naked identifier and raw comparison operator '='."},
        {"file": "bad.sql", "line": 1, "code": "LT01", "msg": "Expected single whitespace between raw comparison operator '=' and numeric literal."},
        {"file": "bad.sql", "line": 1, "code": "LT09", "msg": "Select targets should be on a new line unless there is only one select target."},
        {"file": "bad.sql", "line": 1, "code": "LT14", "msg": "The 'where' keyword should always start a new line."}
      ]
    }
  ]
}
```
5 findings reales con códigos reales (`LT01`, `LT09`, `LT14`); `clean.sql` no genera findings.

### 3. Suite completa del repo (determinismo, dos corridas)

```
=== RUN 1 ===
Ran 596 tests in 16.839s
OK
=== RUN 2 ===
Ran 596 tests in 15.412s
OK
```

## Trade-offs / notas

- **Pin = versión instalada** (4.2.2) en `IntegrationRealSqlfluff`, siguiendo el patrón clippy/govet (no el de ruff que pinea un example fijo). Consecuencia: la integración real corre siempre que sqlfluff esté instalado, sin amarrar el pin a una versión arbitraria del test. Si el entorno tuviera otra versión, `SQLFLUFF_PIN` se adapta y la integración sigue corriendo (no salta por mismatch, porque el pin es lo instalado).
- **Orden de args en `collect`**: `[sqlfluff, lint] + args + files + [--format, json]` (args antes de archivos, `--format json` al final). Verificado que sqlfluff acepta este orden (y también archivos-args-format). Test `test_uses_args_and_files_when_provided` lo fija.
- **`filepath` relativo vs absoluto**: verifiqué que con `cwd=root` y archivo relativo, sqlfluff devuelve `filepath` relativo (`bad.sql`). Aun así `_normalize` relativiza defensivamente a `root` con fallback `as_posix()` (forward-slash) por si viene absoluto u otro drive — idéntico espíritu a `RuffAdapter`.
- Un bug inicial durante el desarrollo: usé `Path(fn).replace("\\","/")` — `Path.replace` es renombrar archivos en disk, no str.replace. Corregido a `Path(fn).as_posix()` (que ya convierte backslash → forward-slash en Windows).
- No se autocorrección de sqlfluff (`--fix`): el gate solo reporta findings, no muta archivos (mismo contrato que los otros 3 adapters).