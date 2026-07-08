#!/usr/bin/env python3
"""complexity_mcp.py — servidor MCP local (stdio, JSON-RPC 2.0) que expone el SUSTRATO
determinista + el rubric gobernado de los contratos CCDD. NO llama a ningún LLM: el cerebro
es el agente anfitrión (Claude Code/Cursor) que invoca estas tools.

Tools:
  measure_complexity(code, filename?)        -> métricas AST reales por función (sin LLM)
  complexity_rubric(agent?)                  -> system/policies/thresholds del contrato FIRMADO
  scan_guardrails(code, agent?)              -> guardrails deterministas del contrato (secretos, anidamiento)
  lint_task_contract(contract_text, test_code?) -> tc_lint determinista sobre un task-contract en memoria
                                                 (anti-desvarío del modelo grande que lo autora)

Transporte: MCP stdio = mensajes JSON-RPC delimitados por salto de línea.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics    # noqa: E402,F401  (registra el backend python al importarse)
import metrics_backends as mb  # noqa: E402
import tc_lint    # noqa: E402
import task_gate  # noqa: E402  (veredicto unificado determinista)

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parent / "contracts"
DEFAULT_AGENT = "complexity-agent"
AGENTS = {"complexity-agent", "pre-complexity-agent", "task-author-agent"}

# Implementador (small executor): lo fija el SERVIDOR/operador, no el LLM. run_ephemeral_agent NO
# acepta model/api_url del llamador (se ignoran): SIEMPRE usa estos. El OPERADOR puede sobreescribir
# por entorno (CCDD_EXECUTOR_MODEL / CCDD_EXECUTOR_API) sin tocar la fuente; el LLM no puede.
# Default validado por benchmark: qwen3-coder:480b cubre de trivial a LeetCode-Hard en ~4-6s a primer
# intento (un modelo más grande no aportó capacidad, solo latencia). Ollama sirve el cloud sin descargar.
DEFAULT_EXECUTOR_MODEL = os.environ.get("CCDD_EXECUTOR_MODEL", "qwen3-coder:480b-cloud")
DEFAULT_EXECUTOR_API = os.environ.get("CCDD_EXECUTOR_API", "http://localhost:11434/v1")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Contrato de ejemplo que lintea verde (verificado en tests/test_mcp_instructions.py). Se incrusta
# en INSTRUCTIONS para que el agente tenga una plantilla válida y no descubra el formato a ciegas.
_MINIMAL_CONTRACT = '''---
task: add-two
intent: Sumar dos enteros.
target: add.py
signature: "def add(a: int, b: int) -> int"
budget: { cyclomatic_max: 3, nesting_max: 1, params_max: 2, lines_max: 10 }
deps_allowed: []
forbids: ["convertir a str"]
tests: tests/test_add.py
test_command: "python -m pytest tests/test_add.py"
test_cwd: "."
spec_version: "0.1"
require_test_approval: false
---

## Intent
Sumar dos enteros y devolver su suma.

## Interface
- Entrada: a, b enteros. Salida: a + b (int).

## Invariants
1. add(a, b) == a + b para todo par de enteros.

## Examples
- add(2, 3) -> 5
- add(0, 0) -> 0

## Do / Don't
- DO: devolver int. DON'T: convertir a str.

## Tests
tests/test_add.py: oraculo independiente con casos fijos.

## Constraints
- Sin deps. PARAR y reportar si el budget no se cumple sin violar la interfaz.
'''

# Se entrega al agente anfitrión en `initialize` (campo MCP `instructions`). Documenta el flujo y
# el formato del contrato de forma EXPLÍCITA, para que el modelo grande no los infiera por
# error-y-reintento (la causa principal de tiempo perdido observada en uso real).
INSTRUCTIONS = """\
ccdd-complexity: sustrato DETERMINISTA para construir código verificado con disciplina CCDD. El
cerebro eres TÚ (el agente anfitrión); estas tools no llaman a ningún LLM salvo run_ephemeral_agent,
que delega la IMPLEMENTACIÓN a un modelo pequeño local y la valida contra un gate determinista.

TU ROL: eres el AUTOR/ORQUESTADOR, NO el implementador. NO escribas tú el código de las funciones
(ni con Write ni de ninguna forma). TODA implementación se delega a run_ephemeral_agent. Si una
función no pasa el gate, NO la implementes vos: re-divídela en sub-funciones más chicas (cada una con
su contrato + tests) y vuelve a delegar. Tú produces contratos, tests y descomposición; el código de
producción lo escribe el implementador. (El gate verifica igual quién sea el autor, pero el
experimento mide al implementador pequeño: si escribís código vos, lo invalidás.)

FLUJO por cada función a implementar:
  1. Redacta un task-contract (front-matter YAML + cuerpo Markdown; formato abajo) y sus
     property-tests congelados (oráculo independiente que NO importa nada del target).
  2. Llama lint_task_contract(contract_text, test_code) y corrige hasta {"ok": true}. NO sigas con
     el lint en rojo: cada finding trae "rule" y "msg" con exactamente qué arreglar.
  3. Crea en disco el target (un stub vacío basta) y el archivo de tests ANTES del paso 4.
  4. run_ephemeral_agent(api_url, model, task_path): el modelo pequeño escribe el código e itera
     contra el gate hasta PASS o agotar iteraciones. Devuelve status PASS/FAIL.

FORMATO DEL CONTRATO (causas típicas de lint en rojo entre corchetes):
  Front-matter, claves REQUERIDAS:
    task: kebab-case atómico
    intent: UNA sola frase, un verbo ("y además ..." la rompe)            [tc-intent-atomic]
    target: ruta relativa al .md del contrato (ej: aacs/schema.py)
    signature: ENTRE COMILLAS, un def parseable (ej: "def f(x: dict) -> str")  [tc-signature-valid]
    target_line: (OPCIONAL) línea de la def objetivo. OBLIGATORIO si el target tiene >1 función/método
                 homónimo (p.ej. `set` en varias clases): sin él el gate devuelve INVALID (ambiguo) en
                 vez de medir la def equivocada. Con un solo match, omitir (back-compat).
    budget: { cyclomatic_max, nesting_max, params_max, lines_max }
    deps_allowed: []        (decláralo aunque sea vacío)
    forbids: [...]          (prohibiciones duras: eval, exec, estado global, ...)
    tests: ruta relativa al .md (ej: tests/test_f.py)
    test_command: comando que corre los tests (ej: "python -m pytest tests/test_f.py")
    test_cwd: (OPCIONAL) directorio desde el que correr test_command, relativo al .md. Por defecto
              es la CARPETA DEL TARGET; pon "." para correr desde la raíz del proyecto (donde el
              target es importable como paquete). Los paths de test_command son relativos a esto.
    spec_version: "0.1"
    require_test_approval: false   (true exige firmar los tests con su tests_sha256)
  Cuerpo: secciones con ## (doble almohadilla): Intent, Interface, Invariants, Examples,
    Do / Don't, Tests, Constraints. Constraints DEBE incluir una regla de parada
    ("PARAR y reportar si ...").                                          [tc-sections, tc-stop-rule]
  NO incluyas el algoritmo ni pseudocódigo de la solución en el contrato: describe QUÉ, no CÓMO.
    El código lo escribe el implementador.                               [tc-no-algorithm]

run_ephemeral_agent: el implementador. **Solo pasás task_path** (ruta ABSOLUTA al .md del contrato);
  el MODELO Y EL ENDPOINT los decide el SERVIDOR — NO los pasás, NO los elegís y NO intentes
  "descubrirlos" curleando /v1/models (el implementador puede ser un modelo cloud que no aparece en
  esa lista). target y tests deben existir antes de llamar.

COMPOSICIÓN (cuando una tarea son varias funciones): tras implementar las funciones hoja, escribe
un contrato de GRUPO (kind: group) que las componga: `children` (lista de .md de las funciones u
otros grupos), `integration_tests` + `integration_test_command` con un oráculo que pruebe el
comportamiento ENSAMBLADO. Para gatear un grupo usá **run_integration_gate(task_path)** (corre sobre los archivos REALES en
disco, porque el test de integración importa los módulos hijos ensamblados). El gate del grupo pasa SOLO si
todas las hijas pasan su gate Y la composición pasa su oráculo. Es recursivo (grupo dentro de grupo:
spec -> tarea -> función). Si una hija falla, NO la implementes vos: re-divídela en piezas más
chicas y reintenta con el implementador.
Para sistemas multi-componente, declara specs compartidas con `conforms_to` (las que el componente
consume) / `produces` (las que produce): backend y front no se comunican; ambos se verifican contra
el MISMO archivo de spec, que el gate exige que exista y esté bien formado.
CHECKLIST DE CIERRE (antes de dar una tarea por terminada corré las CUATRO; no te quedes solo con
la que da verde —el gate de función NO cubre nada de esto):
  - **audit_composition(root)**: ungated_composition = funciones que importan a otras sin un
    kind:group que las gatee. Lo que no agrupás, no se verifica.
  - **audit_orphan_targets(root)**: .py de implementación que no son target de ningún contrato
    (código que entró fuera del flujo gate). Para proyectos 100% CCDD.
  - **audit_annotations(root)**: nombres usados en anotaciones sin importar/definir, project-wide.
    Caza bugs de portabilidad que Python 3.14 (lazy annotations) enmascara en runtime. El fix es
    AGREGAR el import que la firma necesita, NO borrar la anotación.
  - **mutation_audit(task_path)**: fuerza del oráculo. Un mutante sobreviviente = ningún test lo
    cazó (oráculo débil). El fix es AGREGAR un test que mate al mutante, NO tocar el target.
La tarea está terminada cuando las cuatro devuelven ok:true. Que el autor corra solo las que pasan
y declare "todo en verde" es el modo de falla que esta checklist existe para cerrar.

EJEMPLO MÍNIMO que lintea verde (úsalo de plantilla):
""" + _MINIMAL_CONTRACT

TOOLS = [
    {
        "name": "measure_complexity",
        "description": "Mide complejidad por función (ciclomática, anidamiento, nº de parámetros, longitud) "
                       "con el backend del LENGUAJE (python con AST nativo; otros lenguajes vía backend "
                       "registrado, enrutado por 'language' o por la extensión de 'filename'; default python). "
                       "Determinista, sin LLM. Devuelve valores reales y si superan el umbral firmado.",
        "inputSchema": {"type": "object", "required": ["code"], "properties": {
            "code": {"type": "string", "description": "Código a medir."},
            "filename": {"type": "string", "description": "Nombre lógico del archivo (opcional; su extensión "
                         "selecciona backend si no se pasa 'language')."},
            "language": {"type": "string", "description": "Lenguaje del backend (opcional; precede a la "
                         "extensión). Default python (back-compat)."}}},
    },
    {
        "name": "complexity_rubric",
        "description": "Devuelve el criterio GOBERNADO (system + policies + thresholds) del contrato CCDD "
                       "firmado, para que TÚ (el agente) analices con el criterio del equipo, no el tuyo.",
        "inputSchema": {"type": "object", "properties": {
            "agent": {"type": "string", "enum": sorted(AGENTS),
                      "description": "complexity-agent (post-código) o pre-complexity-agent (diseño)."}}},
    },
    {
        "name": "scan_guardrails",
        "description": "Aplica los guardrails deterministas al código: texto-puro compartidos (secretos), "
                       "estructurales calculados con el backend del LENGUAJE (anidamiento profundo, no por "
                       "regex de indentación) y específicos del lenguaje si existen (p. ej. no-eval). El "
                       "lenguaje se toma de 'language' o de la extensión de 'filename' (default python). "
                       "Sin LLM. Devuelve cuáles dispararon, su on_fail y el método (regex/backend).",
        "inputSchema": {"type": "object", "required": ["code"], "properties": {
            "code": {"type": "string"},
            "agent": {"type": "string", "enum": sorted(AGENTS)},
            "language": {"type": "string", "description": "Lenguaje (opcional; precede a la extensión)."},
            "filename": {"type": "string", "description": "Nombre de archivo (opcional; su extensión "
                         "selecciona lenguaje si no se pasa 'language')."}}},
    },
    {
        "name": "lint_task_contract",
        "description": "Valida un TASK-CONTRACT (front-matter YAML + cuerpo Markdown) con tc_lint determinista, "
                       "ANTES de emitirlo al implementador pequeño. Anti-desvarío del modelo grande que lo autora: "
                       "campos requeridos, intent atómico, firma válida (por lenguaje vía el campo opcional "
                       "'language' del front-matter; python con parser nativo, el resto por aridad genérica), "
                       "budget ≤ topes firmados, secciones obligatorias, regla de parada, tests congelados. Pasa "
                       "también test_code para validar que los property-tests existen y referencian la firma. "
                       "Sin LLM. Devuelve {ok, errors, findings}.",
        "inputSchema": {"type": "object", "required": ["contract_text"], "properties": {
            "contract_text": {"type": "string", "description": "El task-contract completo (--- yaml --- + cuerpo)."},
            "test_code": {"type": "string", "description": "Código de los property-tests congelados (opcional pero "
                          "recomendado: sin él la regla tc-tests-frozen falla)."}}},
    },
    {
        "name": "audit_composition",
        "description": "Audita un proyecto (sin LLM, determinista): funciones cuyo target IMPORTA otro target "
                       "sin un contrato kind:group. Distingue deuda de FORMA (el test del composer ejercita los "
                       "hijos reales -> la composición SÍ se verifica vía el gate de la función) de deuda de "
                       "COMPORTAMIENTO (el test mockea o falta -> el ensamble NO se verifica). Devuelve "
                       "{functions, groups, ungated_composition, behavior_unverified, ok}; ok=sin deuda de comportamiento.",
        "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string", "description": "Raíz del proyecto a auditar (default: directorio actual)."}}},
    },
    {
        "name": "audit_orphan_targets",
        "description": "Audita un proyecto (sin LLM, determinista): destaca los .py de implementación "
                       "(excluye tests, __init__, conftest, y módulos de DATOS PUROS —dataclasses sin funciones, "
                       "que no tienen lógica que gatear—) que NO son el target de ningún contrato: código que "
                       "entró FUERA del flujo gate (orquestador implementando directo, glue con lógica, cruft). "
                       "Para proyectos 100% CCDD. Devuelve {py_files, contracts, orphans, ok}.",
        "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string", "description": "Raíz del proyecto a auditar (default: directorio actual)."}}},
    },
    {
        "name": "audit_annotations",
        "description": "Audita un proyecto (sin LLM, determinista, barato): corre el check de anotaciones "
                       "(nombres usados en anotaciones sin importar/definir) sobre TODOS los targets de "
                       "contratos de función, no solo los del diff. Caza project-wide los bugs de portabilidad "
                       "que el runtime (Python 3.14 lazy annotations) enmascara. Devuelve {checked, failures, ok}.",
        "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string", "description": "Raíz del proyecto a auditar (default: directorio actual)."}}},
    },
    {
        "name": "mutation_audit",
        "description": "Mide la FUERZA del oráculo de un contrato (sin LLM, determinista): aplica un set "
                       "fijo de mutaciones al target (flip de comparadores/operadores, bool, return None) y "
                       "corre los tests congelados por cada mutante. Un mutante que PASA los tests = el "
                       "oráculo no lo cazó (test débil). Caro (corre tests por mutante), opt-in. Devuelve "
                       "{mutants, killed, survived, mutation_score, ok}.",
        "inputSchema": {"type": "object", "required": ["task_path"], "properties": {
            "task_path": {"type": "string", "description": "Ruta al contrato .md en disco."}}},
    },
    {
        "name": "run_integration_gate",
        "description": "Gatea un contrato que YA EXISTE EN DISCO (sin sandbox): reusa task_gate.gate sobre los "
                       "archivos REALES del proyecto. Úsalo para contratos kind:group (composición: cada hija pasa "
                       "su gate Y el test de integración prueba la composición ensamblada, importando los módulos "
                       "hijos reales). A diferencia de run_task_gate —que aísla target+tests en un tempdir y NO ve "
                       "otros módulos—, este ve el proyecto completo, que es lo que la composición necesita. "
                       "Devuelve {verdict, stage, ...}.",
        "inputSchema": {"type": "object", "required": ["task_path"], "properties": {
            "task_path": {"type": "string", "description": "Ruta (absoluta o relativa) al contrato .md en disco. "
                          "Para kind:group, sus children e integration_tests se resuelven relativos a él."}}},
    },
    {
        "name": "request_human_attestation",
        "description": "Herramienta que el agente invoca cuando choca de frente contra un umbral estructural (Complexity Gate) "
                       "que NO puede ser simplificado por reglas de negocio. Esta herramienta calcula un Hash Semántico del "
                       "código y emite una petición oficial de firma. Un arquitecto humano revisará el código y, si está "
                       "de acuerdo, firmará la excepción con su clave Ed25519, desbloqueando el gate.",
        "inputSchema": {"type": "object", "required": ["code", "reason"], "properties": {
            "code": {"type": "string", "description": "El código fuente de la función o módulo problemático."},
            "reason": {"type": "string", "description": "Justificación técnica clara de por qué este código NECESITA "
                       "violar el umbral actual (ej. 'Requiere anidamiento nivel 5 por el switch case de negocio X')."},
            "agent": {"type": "string", "enum": sorted(AGENTS), "description": "El agente contra el que corría (default complexity-agent)."},
            "filename": {"type": "string", "description": "Nombre de archivo (opcional)."}
        }},
    },
    {
        "name": "run_ephemeral_agent",
        "description": "Delega un Task Contract al implementador (Small Executor) y lo valida en bucle (max 3) contra task_gate.py hasta PASS o agotar intentos. EL MODELO Y EL ENDPOINT LOS DECIDE EL SERVIDOR — no se pasan ni se eligen desde aquí; tú solo indicas qué contrato implementar. Retorna status y nº de intentos.",
        "inputSchema": {"type": "object", "required": ["task_path"], "properties": {
            "task_path": {"type": "string", "description": "Ruta relativa o absoluta al archivo del Task Contract (.md). ÚNICO parámetro: el modelo lo fija el servidor."}
        }},
    },
    {
        "name": "run_eval_gate",
        "description": "Veredicto DETERMINISTA (Tier 1, sin LLM) de un EVAL-CONTRACT sobre output NO determinista de un "
                       "agente: corre el agente sobre el dataset CONGELADO (firmado con cases_sha256) y aplica checks "
                       "deterministas (schema, contención de términos, citas/groundedness anti-alucinación, PII, "
                       "trayectoria). El complemento del gate de código: aquél verifica CÓDIGO, éste verifica "
                       "COMPORTAMIENTO. PASS si casos intactos + pass_rate ≥ budget + violaciones duras ≤ budget. "
                       "Devuelve {verdict, cases, passed, pass_rate, hard_violations, failing}.",
        "inputSchema": {"type": "object", "required": ["eval_path"], "properties": {
            "eval_path": {"type": "string", "description": "Ruta (absoluta o relativa) al eval-contract .md en disco."}}},
    },
    {
        "name": "eval_rubric",
        "description": "Devuelve el criterio GOBERNADO (system + policies + thresholds + env) del contrato eval-agent "
                       "firmado: la rúbrica con la que el juez Tier 2 (LLM-as-judge, opt-in) evalúa coherencia/utilidad.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "judge_audit",
        "description": "Calibra el JUEZ Tier 2 contra el golden set (análogo a mutation_audit para el oráculo): corre el "
                       "juez sobre los casos con golden_judgment y mide el ACUERDO con el criterio humano. Si el acuerdo "
                       "< judge.agreement_min, falla el JUEZ (no el agente): sus veredictos no son de fiar. Por defecto usa "
                       "el provider 'stub' (determinista, offline). Devuelve {golden_cases, agreement, ok, details}.",
        "inputSchema": {"type": "object", "required": ["eval_path"], "properties": {
            "eval_path": {"type": "string", "description": "Ruta al eval-contract .md en disco."}}},
    },
    {
        "name": "scan_dependencies",
        "description": "Lista los imports top-level del código que NO están en deps_allowed (ni en la stdlib): "
                       "dependencias de tercero no autorizadas (anti-slopsquatting). Determinista, sin LLM, vía "
                       "deps_check.unauthorized_imports. Devuelve {unauthorized: [...]}.",
        "inputSchema": {"type": "object", "required": ["code"], "properties": {
            "code": {"type": "string", "description": "Código a escanear."},
            "deps_allowed": {"type": "array", "description": "Dependencias permitidas (top-level); opcional.",
                             "items": {"type": "string"}},
            "local_roots": {"type": "array", "description": "Directorios de búsqueda locales (opcional): "
                            "imports que resuelvan a un módulo/paquete local bajo alguno de estos roots "
                            "(`<root>/m.py` o `<root>/m/__init__.py`) se eximen. Sin este campo, ningún módulo "
                            "local se exime.", "items": {"type": "string"}}}},
    },
    {
        "name": "check_signature",
        "description": "Conformidad de la firma IMPLEMENTADA vs la esperada (runners/sig_check.py / sig_treesitter.py). "
                       "Compara nombre + nombres de parámetros en orden (ignora anotaciones y defaults). Python usa AST nativo; "
                       "otros lenguajes usan tree-sitter si la gramática está disponible. Determinista, sin LLM. "
                       "Devuelve {mismatch}: '' (vacío) si la firma implementada coincide, "
                       "una cadena no vacía con el desajuste en caso contrario.",
        "inputSchema": {"type": "object", "required": ["source", "fn_name", "expected_signature"], "properties": {
            "source": {"type": "string", "description": "Código fuente donde buscar la función."},
            "fn_name": {"type": "string", "description": "Nombre de la función a verificar."},
            "expected_signature": {"type": "string", "description": "Firma esperada (def parseable, ej: \"def f(x: int) -> str\")."},
            "language": {"type": "string", "description": "Lenguaje del código (optional, default 'python'). Python usa AST nativo; otros lenguajes usan tree-sitter si disponible."},
            "target_line": {"type": "integer", "description": "Línea de la def a verificar (opcional, desambigua funciones homónimas)."}}},
    },
    {
        "name": "check_purity",
        "description": "Marcas de impureza del cuerpo de una función (runners/purity_check.py): Calls al "
                       "denylist (print/open/input/eval/exec/__import__), Global, Nonlocal, Import/ImportFrom. "
                       "Solo stdlib (ast), sin ejecutar el código. [] si la función es pura o no se encuentra. "
                       "Determinista, sin LLM. Devuelve {impurities: [...]}.",
        "inputSchema": {"type": "object", "required": ["source", "fn_name"], "properties": {
            "source": {"type": "string", "description": "Código fuente donde buscar la función."},
            "fn_name": {"type": "string", "description": "Nombre de la función a verificar."},
            "target_line": {"type": "integer", "description": "Línea de la def a verificar (opcional, desambigua funciones homónimas)."}}},
    },
    {
        "name": "check_mutable_defaults",
        "description": "Nombres de parámetros con default mutable (runners/mutdef_check.py): literal "
                       "List/Dict/Set o Call a list/dict/set. Bug clásico de estado compartido entre "
                       "llamadas. Solo stdlib (ast), sin ejecutar el código. [] si no hay o no se encuentra. "
                       "Determinista, sin LLM. Devuelve {mutable_defaults: [...]}.",
        "inputSchema": {"type": "object", "required": ["source", "fn_name"], "properties": {
            "source": {"type": "string", "description": "Código fuente donde buscar la función."},
            "fn_name": {"type": "string", "description": "Nombre de la función a verificar."},
            "target_line": {"type": "integer", "description": "Línea de la def a verificar (opcional, desambigua funciones homónimas)."}}},
    },
    {
        "name": "check_bare_except",
        "description": "Líneas de los manejadores `except:` desnudos (sin tipo) dentro de una función "
                       "(runners/bareexcept_check.py). Bare except traga KeyboardInterrupt/SystemExit y "
                       "enmascara bugs. Solo stdlib (ast), sin ejecutar el código. [] si no hay o no se "
                       "encuentra. Determinista, sin LLM. Devuelve {bare_except_lines: [...]}.",
        "inputSchema": {"type": "object", "required": ["source", "fn_name"], "properties": {
            "source": {"type": "string", "description": "Código fuente donde buscar la función."},
            "fn_name": {"type": "string", "description": "Nombre de la función a verificar."},
            "target_line": {"type": "integer", "description": "Línea de la def a verificar (opcional, desambigua funciones homónimas)."}}},
    },
    {
        "name": "check_asserts",
        "description": "Líneas de los `assert` dentro del cuerpo de una función (runners/assert_check.py), "
                       "incluye anidados. Los asserts en producción se eliminan con -O y dejan de verificar "
                       "invariantes. Solo stdlib (ast), sin ejecutar el código. [] si no hay o no se "
                       "encuentra. Determinista, sin LLM. Devuelve {assert_lines: [...]}.",
        "inputSchema": {"type": "object", "required": ["source", "fn_name"], "properties": {
            "source": {"type": "string", "description": "Código fuente donde buscar la función."},
            "fn_name": {"type": "string", "description": "Nombre de la función a verificar."},
            "target_line": {"type": "integer", "description": "Línea de la def a verificar (opcional, desambigua funciones homónimas)."}}},
    },
    {
        "name": "check_none_cmp",
        "description": "Líneas donde una función compara con None usando ==/!= (runners/nonecmp_check.py), "
                       "incluye anidados. Antipatrón (PEP 8 recomienda `is`/`is not`); además `==` puede "
                       "invocar __eq__ de subtipos. Solo stdlib (ast), sin ejecutar el código. [] si no hay "
                       "o no se encuentra. Determinista, sin LLM. Devuelve {none_eq_lines: [...]}.",
        "inputSchema": {"type": "object", "required": ["source", "fn_name"], "properties": {
            "source": {"type": "string", "description": "Código fuente donde buscar la función."},
            "fn_name": {"type": "string", "description": "Nombre de la función a verificar."},
            "target_line": {"type": "integer", "description": "Línea de la def a verificar (opcional, desambigua funciones homónimas)."}}},
    },
    {
        "name": "run_rules_gate",
        "description": "Aplica los checks DETERMINISTAS de ccdd-gate PROJECT-WIDE por glob desde un rules.yaml "
                       "(lista de {check, files}; checks: bare_except/assert/none_eq/mutable_defaults/purity). "
                       "Idea declarativa estilo autorules pero con árbitro AST insobornable (sin LLM). Vuelve los "
                       "gates de antipatrón política de repo, no solo por contrato. Devuelve {verdict, violations}.",
        "inputSchema": {"type": "object", "properties": {
            "rules_path": {"type": "string", "description": "Ruta al rules.yaml (default: rules.yaml)."},
            "root": {"type": "string", "description": "Raíz del repo a escanear (default: directorio actual)."}}},
    },
    {
        "name": "run_linter_gate",
        "description": "Envuelve LINTERS EXTERNOS deterministas como checks opt-in desde un linters.yaml "
                       "(lista de {tool, version, files?, args?, required?}). Hermano de run_rules_gate pero el "
                       "veredicto lo emite un lexterno invocado como subproceso con salida machine-readable, NO un "
                       "LLM ni AST propio. Version pineada (pin exacto por entrada): version instalada != pin -> "
                       "entorno invalido (no es PASS). Tool ausente + required:false -> skip anunciado; required:true "
                       "-> entorno invalido. HOY solo hay adaptador ruff (ruff NO es dependencia del paquete). "
                       "Devuelve {ok, results:[{tool, version, skipped?, findings:[{file,line,code,msg}]}]}.",
        "inputSchema": {"type": "object", "properties": {
            "linters_path": {"type": "string", "description": "Ruta al linters.yaml (default: linters.yaml)."},
            "root": {"type": "string", "description": "Raíz del repo a escanear (default: directorio actual)."}}},
    },
]


def _agent_dir(agent):
    a = agent if agent in AGENTS else DEFAULT_AGENT
    return CONTRACTS / a, a


def measure_complexity(args):
    fname = args.get("filename", "snippet.py")
    try:
        backend = mb.get_backend(language=args.get("language"), filename=fname)
    except KeyError:
        return {"error": "sin backend de métricas para el lenguaje/extensión pedido",
                "language": args.get("language"), "filename": fname,
                "available_languages": mb.supported_languages()}
    return backend.extract_source(args["code"], fname)


def complexity_rubric(args):
    d, a = _agent_dir(args.get("agent", DEFAULT_AGENT))
    read = lambda f: (d / f).read_text(encoding="utf-8") if (d / f).exists() else ""
    return {"agent": a, "contract_dir": d.name,
            "system": read("system.txt"), "policies": read("policies.txt"),
            "thresholds": read("thresholds.txt"), "environment": read("env.txt")}


# Guardrails ESTRUCTURALES: dependen de las métricas, no de un patrón de texto. Se calculan con
# el backend del lenguaje (no con el regex de indentación, que asume Python). id -> métrica/umbral.
STRUCTURAL_GUARDRAILS = {"deep-nesting": ("nesting_depth", mb.RED["nesting_depth"])}


def _lang_guardrails(language):
    """Guardrails específicos del lenguaje (opt-in) desde guardrails_lang.yaml. [] si no hay."""
    import yaml
    f = HERE / "guardrails_lang.yaml"
    if not f.exists():
        return []
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get(language, [])


# Mapa extensión -> lenguaje para seleccionar guardrails por lenguaje, INDEPENDIENTE de que
# exista un backend de métricas (los guardrails de texto/lenguaje aplican aunque no haya backend).
_EXT_LANG = {".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "typescript",
             ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
             ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby"}


def _resolve_language(args):
    """language explícito > lenguaje por la extensión de filename > default (python)."""
    if args.get("language"):
        return args["language"]
    fn = args.get("filename") or ""
    if "." in fn:
        return _EXT_LANG.get("." + fn.rsplit(".", 1)[1].lower(), mb.DEFAULT_LANGUAGE)
    return mb.DEFAULT_LANGUAGE


def _eval_structural(gid, code, language):
    """Evalúa un guardrail estructural con el backend del lenguaje. None si no hay backend o el
    código no parsea (el caller cae al regex del propio guardrail)."""
    metric, limit = STRUCTURAL_GUARDRAILS[gid]
    try:
        fns = mb.get_backend(language=language).measure(code)
    except (KeyError, SyntaxError, ValueError):
        return None
    return any(f[metric] >= limit for f in fns)


def scan_guardrails(args):
    import yaml
    d, a = _agent_dir(args.get("agent", DEFAULT_AGENT))
    code = args["code"]
    language = _resolve_language(args)
    c = yaml.safe_load((d / "context.yaml").read_text(encoding="utf-8"))
    results = []
    for g in list(c["contract"].get("guardrails", [])) + list(_lang_guardrails(language)):
        gid = g["id"]
        if gid in STRUCTURAL_GUARDRAILS:  # estructural: backend del lenguaje (no el regex)
            fired = _eval_structural(gid, code, language)
            if fired is not None:
                results.append({"id": gid, "fired": fired, "on_fail": g.get("on_fail"),
                                "method": "backend", "language": language})
                continue  # sin backend: cae al regex de abajo (degradación)
        if g.get("type") == "regex_deny":  # texto-puro compartido (secretos, no-eval, …) o fallback
            fired = bool(re.search(g["pattern"], code, re.MULTILINE))
            results.append({"id": gid, "fired": fired, "on_fail": g.get("on_fail"),
                            "method": "regex", "language": language})
        # otros tipos (json_schema, reference_check): no los evalúa este scan (igual que antes)
    return {"agent": a, "language": language, "guardrails": results,
            "blocked": any(r["fired"] and r["on_fail"] == "abort" for r in results)}


def lint_task_contract(args):
    """Lintea un task-contract en memoria. Escribe contrato (+ tests si vienen) a un tempdir
    para que las reglas que tocan el filesystem (tc-tests-frozen) funcionen, y corre tc_lint."""
    fm, _ = tc_lint.split_front_matter(args["contract_text"].replace("\r\n", "\n"))
    tests_name = (fm or {}).get("tests", "frozen_tests.py")
    with tempfile.TemporaryDirectory() as d:
        task = Path(d) / "task.md"
        task.write_text(args["contract_text"], encoding="utf-8")
        if "test_code" in args:
            # Respeta el subdirectorio de `tests:` creando los dirs intermedios; nunca escribe
            # fuera del tempdir (una ruta con `..`/absoluta cae al basename dentro del tempdir).
            base = Path(d)
            tp = base / tests_name
            try:
                tp.resolve().relative_to(base.resolve())
            except ValueError:
                tp = base / Path(tests_name).name
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(args["test_code"], encoding="utf-8")
        findings = tc_lint.lint(task)
    errors = sum(1 for f in findings if f["level"] == "error")
    return {"ok": errors == 0, "errors": errors,
            "warnings": len(findings) - errors, "findings": findings,
            "tests_provided": "test_code" in args}


def audit_composition(args):
    """Surfacer determinista de composición sin gatear (ver runners/audit_composition.py)."""
    import audit_composition as _ac
    return _ac.audit(args.get("root") or ".")


def audit_orphan_targets(args):
    """Surfacer determinista de código fuera del flujo de contrato (ver audit_orphan_targets.py)."""
    import audit_orphan_targets as _ao
    return _ao.audit(args.get("root") or ".")


def audit_annotations(args):
    """Scan project-wide del gate de anotaciones (ver runners/audit_annotations.py)."""
    import audit_annotations as _aa
    return _aa.audit(args.get("root") or ".")


def mutation_audit(args):
    """Fuerza del oráculo vía mutation testing determinista (ver runners/mutation_audit.py)."""
    import mutation_audit as _ma
    return _ma.audit(args.get("task_path") or "")


def run_integration_gate(args):
    """Gatea un contrato YA EXISTENTE en disco (sin sandbox), reusando task_gate.gate sobre los
    archivos reales. Para kind:group, el test de integración importa los módulos hijos ensamblados;
    por eso se gatea en disco, no en un tempdir aislado. Devuelve el verdict de task_gate."""
    path = args.get("task_path")
    if not isinstance(path, str) or not path or not Path(path).exists():
        return {"verdict": "INVALID", "stage": "contract", "detail": f"contrato no encontrado en disco: {path}"}
    return task_gate.gate(path)


def request_human_attestation(args):
    code = args.get("code", "")
    reason = args.get("reason", "")
    agent = args.get("agent", DEFAULT_AGENT)
    fname = args.get("filename", "snippet.py")
    if not code or not reason:
        return {"error": "Falta el código o la justificación (reason)."}

    try:
        import semantic_hash
        ext = Path(fname).suffix or ".py"
        h = semantic_hash.get_semantic_hash(code, ext)
    except Exception:
        import hashlib
        h = hashlib.sha256(code.encode("utf-8")).hexdigest()

    out_dir = CONTRACTS / agent / "pending_attestations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{h}.json"

    data = {
        "hash": h,
        "filename": fname,
        "reason": reason,
        "code": code
    }
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "Atestación solicitada",
        "hash": h,
        "message": f"Se ha registrado la petición oficial para el hash {h}. Avisa al arquitecto humano que debe revisar esta petición para desbloquear el gate."
    }

class _BraceScanner:
    """Recorre `source` desde la llave de apertura hasta su cierre balanceado,
    ignorando llaves dentro de strings y comentarios (// y /* */). Cada modo
    (comentario de línea, comentario de bloque, string, código) tiene su propio
    consumidor pequeño: mantiene la complejidad ciclomática de cada paso baja."""

    def __init__(self, source, start):
        self.src = source
        self.i = start
        self.depth = 0
        self.string_char = None
        self.escape = False
        self.in_line_comment = False
        self.in_block_comment = False

    def _peek(self):
        return self.src[self.i + 1] if self.i + 1 < len(self.src) else ""

    def _consume_line_comment(self, c):
        if c == "\n":
            self.in_line_comment = False
        self.i += 1

    def _consume_block_comment(self, c):
        if c == "*" and self._peek() == "/":
            self.in_block_comment = False
            self.i += 2
        else:
            self.i += 1

    def _consume_string(self, c):
        if self.escape:
            self.escape = False
        elif c == "\\":
            self.escape = True
        elif c == self.string_char:
            self.string_char = None
        self.i += 1

    def _consume_code(self, c):
        """Devuelve el índice de fin (exclusivo) si se cierra el bloque, si no None.
        Guard clauses secuenciales (no if/elif) para mantener el anidamiento plano."""
        nxt = self._peek()
        if c == "/" and nxt == "/":
            self.in_line_comment = True
            self.i += 2
            return None
        if c == "/" and nxt == "*":
            self.in_block_comment = True
            self.i += 2
            return None
        if c in ("'", '"', "`"):
            self.string_char = c
            self.i += 1
            return None
        if c == "{":
            self.depth += 1
            self.i += 1
            return None
        if c == "}":
            self.depth -= 1
            self.i += 1
            return self.i if self.depth == 0 else None
        self.i += 1
        return None

    def _active_consumer(self):
        """Selecciona el consumidor según el modo actual (sin anidar ramas)."""
        if self.in_line_comment:
            return self._consume_line_comment
        if self.in_block_comment:
            return self._consume_block_comment
        if self.string_char is not None:
            return self._consume_string
        return self._consume_code

    def find_end(self):
        """Índice de fin (exclusivo) del bloque, o -1 si no balancea."""
        while self.i < len(self.src):
            end = self._active_consumer()(self.src[self.i])
            if end is not None:
                return end
        return -1


def _find_block_start(source, signature):
    """(idx_firma, idx_llave_apertura). (-1, -1) si no se encuentra."""
    idx = source.find(signature)
    if idx == -1:
        return -1, -1
    if "{" in signature:
        return idx, idx + signature.rfind("{")
    return idx, source.find("{", idx + len(signature))


def extract_brace_block(source, signature):
    idx, start_brace = _find_block_start(source, signature)
    if idx == -1 or start_brace == -1:
        return None, -1, -1
    end = _BraceScanner(source, start_brace).find_end()
    if end == -1:
        return None, -1, -1
    return source[idx:end], idx, end

def _prepare_ephemeral_task(args):
    """Carga el task-contract y el target. Devuelve (ctx, None) o (None, error_dict)."""
    task_path = args.get("task_path")
    tp = Path(task_path)
    if not tp.exists():
        return None, {"status": "FAIL", "reason": f"Task file no encontrado: {task_path}"}
    try:
        task_content = tp.read_text(encoding="utf-8")
        fm, _body = tc_lint.split_front_matter(task_content)
        target = tp.parent / fm["target"]
        if not target.exists():
            return None, {"status": "FAIL", "reason": f"Target no encontrado: {target}"}
        original_source = target.read_text(encoding="utf-8")
    except Exception as e:
        return None, {"status": "FAIL", "reason": f"Error parseando: {e}"}
    return {
        "tp": tp,
        # El modelo/endpoint los fija el SERVIDOR, no el llamador: se ignora cualquier model/api_url
        # que venga en args. Así el LLM no puede elegir ni "descubrir" el implementador.
        "model": DEFAULT_EXECUTOR_MODEL,
        "api_url": DEFAULT_EXECUTOR_API,
        "task_content": task_content,
        "target": target,
        "original_source": original_source,
        "signature": fm.get("signature", ""),
    }, None


def _build_ephemeral_prompts(ctx):
    """Prompts iniciales + bloque a reemplazar. Devuelve (sys, user, block, start, end)."""
    signature = ctx["signature"]
    target = ctx["target"]
    original_source = ctx["original_source"]
    task_content = ctx["task_content"]

    target_block, start_idx, end_idx = None, -1, -1
    # Intento de compactación (Tree-shaking estático vía firmas)
    if signature and target.suffix in [".js", ".ts", ".java", ".c", ".cpp", ".cs"]:
        target_block, start_idx, end_idx = extract_brace_block(original_source, signature)

    if target_block:
        sys_prompt = "Eres un Small Executor experto en refactorización. Se te dará UNA FUNCIÓN aislada. Devuelve la función refactorizada completa y SI LO NECESITAS, incluye funciones auxiliares ANTES o DESPUÉS de la principal. REGLA CRÍTICA: DEBES MANTENER LA FIRMA DE LA FUNCIÓN ORIGINAL EXACTAMENTE INTACTA."
        user_prompt = f"### TASK CONTRACT:\n{task_content}\n\n### FIRMA ORIGINAL REQUERIDA:\n{signature}\n\n### FUNCIÓN AISLADA (Compactada):\n```\n{target_block}\n```"
    else:
        sys_prompt = "Eres un Small Executor experto en refactorización orientada a métricas de complejidad ciclomática."
        user_prompt = f"### TASK CONTRACT:\\n{task_content}\\n\\n### CODIGO FUENTE COMPLETO:\\n```\\n{original_source}\\n```\\n\\nDevuelve TODO el archivo refactorizado dentro de un bloque markdown de código (```)."
    return sys_prompt, user_prompt, target_block, start_idx, end_idx


def _sse_delta_content(data_str):
    """Extrae delta.content de una línea SSE de chat completions ('' si no aplica)."""
    try:
        delta = json.loads(data_str)["choices"][0].get("delta", {})
    except json.JSONDecodeError:
        return ""
    return delta.get("content", "")


def _read_sse_content(response):
    """Acumula el content del stream SSE hasta [DONE]. Devuelve (content, timed_out)."""
    import socket
    content = ""
    try:
        for line in response:
            if not line.startswith(b"data: "):
                continue
            data_str = line[6:].decode("utf-8").strip()
            if data_str == "[DONE]":
                break
            content += _sse_delta_content(data_str)
    except socket.timeout:
        return content, True
    return content, False


def _stream_completion(api_url, model, messages):
    """Llama al LLM en streaming. Devuelve (partial_content, timed_out, error_dict)."""
    import urllib.request
    import socket

    data = json.dumps({"model": model, "messages": messages, "temperature": 0.2,
                       "max_tokens": 8000, "stream": True}).encode("utf-8")
    req = urllib.request.Request(f"{api_url}/chat/completions", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            content, timed_out = _read_sse_content(response)
            return content, timed_out, None
    except socket.timeout:
        return "", True, None
    except Exception as e:
        return "", False, {"reason": f"Error conectando al LLM: {e}"}


def _extract_new_code(messages, partial_content):
    """Une las continuaciones previas y extrae el bloque de código markdown."""
    full_answer = "".join(m["content"] for m in messages if m["role"] == "assistant")
    full_answer += partial_content
    code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", full_answer, re.DOTALL)
    new_code = code_match.group(1).strip() if code_match else full_answer.strip()
    return new_code, full_answer


def _apply_new_code(target, new_code, target_block, original_source, start_idx, end_idx):
    if target_block:
        merged = original_source[:start_idx] + new_code + original_source[end_idx:]
        target.write_text(merged, encoding="utf-8")
    else:
        target.write_text(new_code, encoding="utf-8")


def _complexity_feedback(gate_json, signature):
    """Feedback específico de gate2-complexity, o '' si no aplica."""
    over_budget = gate_json.get("over_budget", [])
    actual = limit = cyclo_delta = 0
    for ob in over_budget:
        if "cyclomatic=" in ob and "cyclomatic_max=" in ob:
            parts = re.findall(r"\d+", ob)
            if len(parts) >= 2:
                actual, limit = int(parts[0]), int(parts[1])
                cyclo_delta = actual - limit
    if cyclo_delta <= 0:
        return ""
    return (
        "[!] ÉXITO SINTÁCTICO: ¡Tu código superó las pruebas y es válido!\n\n"
        f"[!] ALERTA MATEMÁTICA: Sin embargo, la complejidad ciclomática actual es {actual}, y el MÁXIMO ESTRICTO permitido es {limit}. ¡ESTÁS EXCEDIDO POR {cyclo_delta} PUNTOS!\n\n"
        "[!] HEURÍSTICA OBLIGATORIA: Para reducir la complejidad drásticamente, NO intentes reescribir todo en la misma función con retornos tempranos. DEBES EXTRAER bloques lógicos (validaciones, iteraciones, branches complejos) a NUEVAS sub-funciones auxiliares privadas que sean llamadas desde la función principal. Escribe estas sub-funciones en el mismo bloque markdown.\n"
        f"[!] REGLA CRÍTICA: La función principal DEBE mantener exactamente esta firma: `{signature}`. No la borres, no la renombres, y no la conviertas en arrow function si no lo era. MANTÉN LOS TESTS PASANDO.\n\n"
    )


def _stage_feedback(gate_json, signature):
    """Feedback específico según la etapa del gate que falló."""
    stage = gate_json.get("stage")
    if stage == "gate2-complexity":
        return _complexity_feedback(gate_json, signature)
    if stage == "gate1-tests":
        error_output = gate_json.get("output", "Error desconocido en los tests.")
        return (f"[!] ALERTA SINTÁCTICA / TESTS: La ejecución del código falló. Revisa el siguiente error que lanzó el validador (puede ser un error de sintaxis o un test fallido):\n\n```\n{error_output}\n```\n\n"
                "[!] INSTRUCCIÓN: Corrige EXACTAMENTE este error lógico o de sintaxis. Asegúrate de que el código sea Javascript/TypeScript válido y que cumpla la firma requerida.\n\n")
    return ""


def _build_feedback(output_str, signature):
    """Construye el prompt de feedback cuantitativo a partir del output del gate."""
    feedback = f"El validador matemático rechazó tu código. Output original:\n{output_str}\n\n"
    try:
        match = re.search(r'(\{.*"verdict":.*"FAIL".*\})', output_str, re.DOTALL)
        if match:
            feedback += _stage_feedback(json.loads(match.group(1)), signature)
    except Exception:
        pass
    feedback += "Por favor genera el código DESDE CERO aplicando estas correcciones. NO repitas el código roto."
    return feedback


def run_ephemeral_agent(args):
    import subprocess

    ctx, error = _prepare_ephemeral_task(args)
    if error:
        return error

    sys_prompt, user_prompt, target_block, start_idx, end_idx = _build_ephemeral_prompts(ctx)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    proc = None
    max_iterations = 3
    gate_script = HERE / "task_gate.py"
    for i in range(max_iterations):
        partial_content, timed_out, error = _stream_completion(ctx["api_url"], ctx["model"], messages)
        if error:
            return {"status": "FAIL", "iteration": i + 1, **error}

        if timed_out and partial_content:
            messages.append({"role": "assistant", "content": partial_content})
            messages.append({"role": "user", "content": "Se alcanzó el timeout. Continúa generando el código EXACTAMENTE donde te quedaste (no repitas el inicio, solo escupe la continuación)."})
            continue  # consume una iteración del límite lógico del Gate

        new_code, full_answer = _extract_new_code(messages, partial_content)
        print(f"\n=== LLM OUTPUT ITERATION {i+1} ===\n{full_answer}\n================================\n", file=sys.stderr)
        _apply_new_code(ctx["target"], new_code, target_block, ctx["original_source"], start_idx, end_idx)

        proc = subprocess.run([sys.executable, str(gate_script), str(ctx["tp"])],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0:
            return {"status": "PASS", "iterations": i + 1, "gate_output": proc.stdout}

        feedback_prompt = _build_feedback(proc.stdout or proc.stderr, ctx["signature"])
        # Stateless feedback: no incluimos full_answer para que el LLM no se contamine con su propia basura
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt + "\n\n### FEEDBACK DEL INTENTO ANTERIOR:\n" + feedback_prompt},
        ]

    # Restaurar si falló
    ctx["target"].write_text(ctx["original_source"], encoding="utf-8")
    return {"status": "FAIL", "iterations": max_iterations, "reason": "Max iteraciones",
            "last_gate": (proc.stdout or proc.stderr) if proc else ""}


def run_eval_gate(args):
    """Veredicto Tier 1 de un eval-contract YA EN DISCO (ver runners/eval_gate.py). Sin LLM."""
    import eval_gate as _eg
    path = args.get("eval_path")
    if not isinstance(path, str) or not path or not Path(path).exists():
        return {"verdict": "INVALID", "stage": "contract", "detail": f"eval-contract no encontrado en disco: {path}"}
    return _eg.gate(path)


def eval_rubric(args):
    """system/policies/thresholds/env del contrato eval-agent firmado (rúbrica del juez Tier 2)."""
    d = CONTRACTS / "eval-agent"
    read = lambda f: (d / f).read_text(encoding="utf-8") if (d / f).exists() else ""
    return {"agent": "eval-agent", "system": read("system.txt"), "policies": read("policies.txt"),
            "thresholds": read("thresholds.txt"), "environment": read("env.txt")}


def judge_audit(args):
    """Calibra el juez Tier 2 contra el golden set (ver runners/judge_audit.py). Provider stub por defecto."""
    import judge_audit as _ja
    path = args.get("eval_path")
    if not isinstance(path, str) or not path or not Path(path).exists():
        return {"ok": False, "detail": f"eval-contract no encontrado en disco: {path}"}
    return _ja.audit(path, provider=args.get("provider", "stub"), api_url=args.get("api_url", ""))


def scan_dependencies(args):
    """Imports top-level no autorizados (anti-slopsquatting) vía deps_check.unauthorized_imports.
    Opcional: `local_roots` (lista de dirs) exime imports que resuelvan a módulos/paquetes locales
    bajo esos roots (mismo mecanismo que el gate 4). Sin ese campo, comportamiento previo intacto."""
    import deps_check
    return {"unauthorized": deps_check.unauthorized_imports(
        args["code"], args.get("deps_allowed") or [], local_roots=args.get("local_roots"))}


def check_signature(args):
    """Conformidad de firma implementada vs esperada (runners/sig_check.py / sig_treesitter.py).
    Python usa AST nativo; otros lenguajes usan tree-sitter si disponible. Sin LLM."""
    lang = args.get("language", "python").lower()
    if lang == "python":
        import sig_check
        return {"mismatch": sig_check.signature_mismatch(args["source"], args["fn_name"], args["expected_signature"], target_line=args.get("target_line"))}
    else:
        import sig_treesitter
        mismatch = sig_treesitter.check_signature_src(args["source"], args["fn_name"], args["expected_signature"], lang, target_line=args.get("target_line"))
        return {"mismatch": mismatch}


def check_purity(args):
    """Marcas de impureza del cuerpo de una función (runners/purity_check.py). Sin LLM."""
    import purity_check
    return {"impurities": purity_check.impure_operations(args["source"], args["fn_name"], args.get("target_line"))}


def check_mutable_defaults(args):
    """Nombres de params con default mutable (runners/mutdef_check.py). Sin LLM."""
    import mutdef_check
    return {"mutable_defaults": mutdef_check.mutable_defaults(args["source"], args["fn_name"], args.get("target_line"))}


def check_bare_except(args):
    """Líneas de manejadores `except:` desnudos en una función (runners/bareexcept_check.py). Sin LLM."""
    import bareexcept_check
    return {"bare_except_lines": bareexcept_check.bare_except_lines(args["source"], args["fn_name"], args.get("target_line"))}


def check_asserts(args):
    """Líneas de `assert` en el cuerpo de una función (runners/assert_check.py). Sin LLM."""
    import assert_check
    return {"assert_lines": assert_check.assert_lines(args["source"], args["fn_name"], args.get("target_line"))}


def check_none_cmp(args):
    """Líneas donde una función compara con None por ==/!= (runners/nonecmp_check.py). Sin LLM."""
    import nonecmp_check
    return {"none_eq_lines": nonecmp_check.none_eq_lines(args["source"], args["fn_name"], args.get("target_line"))}


def run_rules_gate(args):
    """Aplica checks deterministas project-wide por glob desde un rules.yaml (ver runners/rules_gate.py)."""
    import rules_gate
    rules_path = args.get("rules_path", "rules.yaml")
    if not Path(rules_path).exists():
        return {"verdict": "INVALID", "detail": f"rules.yaml no encontrado: {rules_path}"}
    return rules_gate.gate(rules_path, args.get("root", "."))


def run_linter_gate(args):
    """Linters externos deterministas desde un linters.yaml (ver runners/linter_gate.py). Sin LLM:
    invoca el linter pineado como subproceso y normaliza su salida. gate() devuelve (exit, payload);
    el exit queda en el servidor (MCP no propaga código de salida), la tool devuelve el payload."""
    import linter_gate
    linters_path = args.get("linters_path", "linters.yaml")
    if not Path(linters_path).exists():
        return {"ok": False, "error": f"linters.yaml no encontrado: {linters_path}", "results": []}
    _exit, payload = linter_gate.gate(linters_path, args.get("root", "."))
    return payload


DISPATCH = {"measure_complexity": measure_complexity,
            "complexity_rubric": complexity_rubric,
            "scan_guardrails": scan_guardrails,
            "lint_task_contract": lint_task_contract,
            "run_integration_gate": run_integration_gate,
            "audit_composition": audit_composition,
            "audit_orphan_targets": audit_orphan_targets,
            "audit_annotations": audit_annotations,
            "mutation_audit": mutation_audit,
            "request_human_attestation": request_human_attestation,
            "run_ephemeral_agent": run_ephemeral_agent,
            "run_eval_gate": run_eval_gate,
            "eval_rubric": eval_rubric,
            "judge_audit": judge_audit,
            "scan_dependencies": scan_dependencies,
            "check_signature": check_signature,
            "check_purity": check_purity,
            "check_mutable_defaults": check_mutable_defaults,
            "check_bare_except": check_bare_except,
            "check_asserts": check_asserts,
            "check_none_cmp": check_none_cmp,
            "run_rules_gate": run_rules_gate,
            "run_linter_gate": run_linter_gate}


def send(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_tools_call(mid, params):
    name = params["name"]
    fn = DISPATCH.get(name)
    if not fn:
        return send(mid, error={"code": -32601, "message": f"tool desconocida: {name}"})
    try:
        out = fn(params.get("arguments", {}))
    except Exception as e:
        return send(mid, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
    return send(mid, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]})


def handle(msg):
    # ifs planos con return temprano (no elif): evita el artefacto de anidamiento del AST.
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return send(mid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "ccdd-complexity-mcp", "version": "0.1"},
                          "instructions": INSTRUCTIONS})
    if method == "tools/list":
        return send(mid, {"tools": TOOLS})
    if method == "tools/call":
        return handle_tools_call(mid, msg["params"])
    if mid is None:
        return None  # notificación (p.ej. notifications/initialized): no se responde
    return send(mid, error={"code": -32601, "message": f"método no soportado: {method}"})


def main():
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle(json.loads(line))


if __name__ == "__main__":
    main()
