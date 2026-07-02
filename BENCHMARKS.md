# Benchmarks

Dos cosas distintas y honestamente etiquetadas:

1. **Benchmark del gate** — determinista, reproducible en cualquier máquina. Es un benchmark de verdad.
2. **Economía con modelos** — *ilustrativo*, no riguroso (N pequeño, una corrida, atado a tu hardware/modelo/precios). No es un leaderboard.

---

## 1. Gate determinista (reproducible)

`python benchmarks/bench_gate.py` — sin LLM, sin red, mismo resultado corrida a corrida.

| Operación | Costo | Tokens |
|---|---|---|
| `metrics.functions_metrics` (AST) | ~0.23 ms/op | 0 |
| `tc_lint.lint` (valida un task-contract) | ~1.8 ms/op | 0 |
| `task_gate.gate` (veredicto pleno: lint + complejidad + tests) | ~98 ms/op | 0 |

*Medido en Windows, Python 3.14, una corrida. Reproducí con el script; los números absolutos
varían por máquina, el orden de magnitud no.*

**Lectura honesta:** las **métricas de complejidad** (AST) son **sub-milisegundo**; el **lint** del
task-contract es de **un dígito de milisegundos** (~1.8 ms). Los ~98 ms del veredicto pleno son
**ejecutar tus property-tests congelados** (aquí 500 iteraciones por test en un subproceso) — algo
que correrías igual. La lógica de decisión del gate (métricas + lint) es de **orden milisegundo**;
el veredicto en sí no agrega costo perceptible.

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
