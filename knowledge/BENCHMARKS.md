# Benchmarks

Dos cosas distintas y honestamente etiquetadas:

1. **Benchmark del gate** — determinista, reproducible en cualquier máquina. Es un benchmark de verdad.
2. **Economía con modelos** — *ilustrativo*, no riguroso (N pequeño, una corrida, atado a tu hardware/modelo/precios). No es un leaderboard.

---

## 1. Gate determinista (reproducible)

`python benchmarks/bench_gate.py` — sin LLM, sin red, mismo resultado corrida a corrida.

| Operación | Costo | Tokens |
|---|---|---|
| `metrics.functions_metrics` (AST) | ~0.28 ms/op | 0 |
| `tc_lint.lint` (valida un task-contract) | ~0.71 ms/op | 0 |
| `task_gate.gate` (veredicto pleno: lint + complejidad + tests) | ~81 ms/op | 0 |

*Medido en Windows, Python 3.14, una corrida. Reproducí con el script; los números absolutos
varían por máquina, el orden de magnitud no.*

**Lectura honesta:** la **lógica del gate** (métricas + lint) es **sub-milisegundo**. Los ~81 ms
del veredicto pleno son **ejecutar tus property-tests congelados** (aquí 500 iteraciones por test
en un subproceso) — algo que correrías igual. El veredicto en sí no agrega costo perceptible.

**El punto:** la verificación que en un loop agéntico sería una *review por LLM* (~1–2k tokens de
entrada + segundos de latencia + costo de API, y **no determinista**) aquí es **0 tokens, sin red,
y byte-idéntica**. Eso es lo que el gate reemplaza.

---

## 2. Economía grande/pequeño vs loop de modelo grande (ILUSTRATIVO)

Lote real corrido con `runners/measure.py` sobre 4 task-contracts (`clamp`, `popcount`,
`hamming`, `chunk`), implementador **gemma-4-12b** local (LM Studio), escalado a un modelo mayor.

**Resultado de implementación:** 4/4 PASS **al primer intento**, **0 escalados**.

| Métrica | Nuestro flujo | Loop de modelo grande |
|---|---|---|
| Implementación (4 tasks) | $0 (modelo local) | incluido abajo |
| Validación / veredicto | $0 (gate determinista) | — (no tiene; el modelo se auto-juzga) |
| **Solo el loop** | **$0** | **~$0.138** |

→ Solo el loop: **100% de ahorro de API.** Pero ese titular **no es la cuenta completa.**

**Costo total honesto (incluyendo autoría + auditoría, que van en el modelo grande):**

| | Nuestro flujo (1ª vez) | Loop de modelo grande |
|---|---|---|
| Autoría contrato+tests (grande) | ~$0.26 | — |
| Auditoría de tests (grande) | ~$0.13 | — |
| Implementación + veredicto | $0 | ~$0.138 |
| **TOTAL primera vez** | **~$0.38** | **~$0.138** |

→ En tareas **triviales de un tiro, este flujo es ~2.8× MÁS caro.** El overhead fijo
(autoría + auditoría) se amortiza a **~3 ejecuciones** (regresión, CI, re-implementación):
desde ahí, cada re-corrida es $0 vs ~$0.138.

### Salvedades (léelas antes de citar cualquier número)
- **N=4, una sola corrida, modelo y hardware específicos.** No es estadística.
- **Precios ilustrativos** ($15/$75 por millón in/out del modelo grande); ajustá a tu proveedor.
- **No se cuenta el cómputo local** del modelo pequeño (real, barato, no es token de API).
- El ahorro **gana por volumen, reuso y dificultad** — NO en el one-shot trivial.
- El gate es tan fuerte como sus property-tests; tests laxos → "ahorro" ilusorio.

### Reproducir
```bash
python runners/measure.py examples/batch/*/task.md \
  --provider openai --model <tu-modelo-chico> \
  --escalate-provider ollama --escalate-model <tu-modelo-grande>
```
`measure.py` registra intentos, escalados y tokens por tier, y calcula el costo con tus precios.

---

## 3. Audits project-wide (reproducible)

`audit_annotations` y `audit_composition` barren todos los contratos de un proyecto. Dos
optimizaciones (commit `5e06e6e`) reducen el costo de los escenarios patológicos sin cambiar el
resultado (ni el orden de `failures`):

- **`audit_annotations` — memoización por target.** Si N contratos apuntan al mismo target, la
  versión ingenua re-leía y re-parseaba (AST + walk de anotaciones) el archivo una vez por
  contrato. La cache memoiza por `(target, language)`: leer+parsear UNA vez por target único.
- **`audit_composition` — hoist O(N²)→O(N).** `_imported_stems(target)` se evaluaba dentro de la
  comprensión `s for s in funcs if s in _imported_stems(target)` → O(N) parseos por stem → O(N²).
  Hoist fuera de la comprensión: un parseo por stem.

Escenario sintético (tempdir borrado al final; mediana de 3 corridas; versión actual del repo,
Windows/Python 3.14):

| Audit | Escenario | Tiempo actual |
|---|---|---|
| `audit_annotations` | 400 contratos → 1 mismo target (200 funciones anotadas) | ~340 ms |
| `audit_composition` | 150 contratos con imports cruzados (cada target importa 2 otros, 8 fns) | ~210 ms |

Speedup medido en el commit `5e06e6e`: **~20x** (`audit_annotations`) y **~29x**
(`audit_composition`). La versión pre-optimización ya no está en el repo, así que esos factores
se citan de aquel commit (no se re-midieron aquí); el tiempo absoluto de arriba es la referencia
actual. Validación: reconstruir el loop naïve inline (sin tocar código del repo) reproduce el
orden de magnitud — ~21x en `audit_annotations` (coherente con ~20x); en `audit_composition` el
factor escala con el costo de parseo del target, por lo que ~29x es la cifra del commit sobre su
escenario y targets más pesados lo amplifican.
