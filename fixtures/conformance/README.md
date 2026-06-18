# Suite de conformancia de métricas (#8)

Oráculo **congelado** que todo backend de métricas debe reproducir. Python define el baseline;
un backend nuevo (tree-sitter/TS, #1) **no se da por bueno hasta pasar esta suite**.

## Estructura
- `manifest.json` — fixtures con valores esperados por métrica (oráculo), notas y divergencias
  permitidas. Es la fuente de verdad; el test `tests/test_conformance.py` lo consume.
- `<lenguaje>/<fixture>.<ext>` — la misma estructura lógica implementada por lenguaje.

## Fixtures (estructura lógica equivalente entre lenguajes)
`simple`, `deep_nesting` (5 niveles), `many_params` (6), `long_function` (>80 líneas),
`boolop_chain`, `comprehension`, `switch_case`.

## Reglas del oráculo
- **Estructurales** (`cyclomatic`, `nesting_depth`, `parameter_count`): deben **coincidir entre
  lenguajes** para la misma estructura lógica.
- `function_length`: depende del formato del lenguaje (las llaves añaden líneas) → se compara
  **por-lenguaje** vía `language_overrides`, no entre lenguajes.
- Divergencias inevitables se declaran en `cross_language_divergence_allowed` (con la razón en
  `note`) y se fijan por-lenguaje en `language_overrides`. Ejemplo ya documentado: en el backend
  Python `match/switch` suma a `cyclomatic` (+1 por rama) pero **no** a `nesting_depth`; un backend
  de otro lenguaje puede contar el `switch` como nivel de anidamiento → se fija su valor en
  `language_overrides`.

## Añadir un lenguaje (p. ej. typescript)
1. Implementar y **registrar** el backend (`metrics_backends.register(...)`).
2. Crear `fixtures/conformance/typescript/<fixture>.ts` para cada fixture (misma lógica).
3. En `manifest.json`, añadir `"typescript": "typescript/<fixture>.ts"` en `sources` de cada fixture.
4. Si alguna métrica diverge justificadamente, fijarla en `language_overrides.typescript` y
   documentar el porqué en `note`.
5. `python -m unittest tests.test_conformance` debe pasar para el nuevo lenguaje.
