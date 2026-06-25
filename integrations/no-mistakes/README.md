# ccdd-gate ↔ no-mistakes

Integración **opcional** de ccdd-gate como **check determinista** dentro del pipeline de entrega de
[no-mistakes](https://github.com/kunchenguid/no-mistakes) (proxy git local → worktree → pipeline →
PR). Capas complementarias: no-mistakes aporta la **entrega** (push→PR→CI, multi-agente, TUI);
ccdd-gate aporta el **veredicto insobornable** (sin LLM) que al pipeline de no-mistakes le falta
—su `review` es IA y su `test`/`lint` autofixean con IA.

## Cómo funciona (camino 1: solo config)
no-mistakes corre `commands.test` como paso determinista; si sale ≠0, escala. Apuntamos ese comando
a `nm_gate.py`, que corre los chequeos project-wide de ccdd-gate **sin LLM** y devuelve un exit code:

- **complejidad** (`repo_gate.py`): ninguna función de producción supera el umbral firmado.
- **anotaciones** (`audit_annotations`): sin nombres en anotaciones sin importar/definir.
- **composición** (`audit_composition`): sin deuda de composición sin gatear.

```bash
python integrations/no-mistakes/nm_gate.py [root]   # exit 0 = verde · 1 = algún check falló
```

## Instalación
1. Copiá `no-mistakes.yaml.example` como `.no-mistakes.yaml` en la raíz del repo y **mergealo a la
   rama default** (no-mistakes solo honra `commands`/`allow_repo_commands` desde la rama confiable).
2. Ajustá la ruta del comando si vendorizás/instalás ccdd-gate en otro lugar.

## La clave: `auto_fix.test: 0`
Por defecto no-mistakes manda los fallos de `test` a **su agente para autofixear** — eso
reintroduce el actor no determinista que ccdd-gate existe para evitar. Con `auto_fix.test: 0` el
fallo del gate **escala al humano** (o a tu flujo de delegación a glm), preservando el veredicto
determinista. Entrega cómoda de no-mistakes + gate insobornable de ccdd-gate.

## Validación E2E (hallazgos reales, verificados)
Se probó end-to-end contra un repo real y un sandbox local. Resultado honesto:

- ✅ **`commands.test` SÍ se honra**: el log del step muestra `running tests: python <check>` — el check
  determinista de ccdd-gate **corre dentro del pipeline**. La integración (camino 1) es viable.
- ⚠️ **El step `test` de no-mistakes, además del comando, invoca al AGENTE** para "gather test
  evidence" cuando hay user-intent (y `axi run` exige `--intent`). Si ese agente no está operativo
  headless, el step falla aunque el comando determinista haya pasado.
- ✅ **No hace falta auth de Anthropic**: se puede enrutar el `claude` de no-mistakes a **ollama/glm**
  (igual que `ollama launch claude`) con env `ANTHROPIC_BASE_URL=http://localhost:11434`,
  `ANTHROPIC_API_KEY=ollama`, `ANTHROPIC_MODEL=<modelo>`. Verificado: `claude -p` responde vía glm sin 401.
- ⛔ **Cabo no resuelto (mecánica del daemon de no-mistakes en Windows):** el daemon es un servicio
  gestionado que no recoge el env de la shell; y apuntar el agente al wrapper glm vía
  `agent_path_override` **cuelga el arranque del daemon** ("not responsive within 15s"), porque sondea
  el agente al iniciar y ese probe vía glm excede su ventana. Con config default el daemon arranca bien.

**Conclusión:** la parte que aporta valor —el gate determinista como `commands.test`— funciona. El
E2E 100% verde depende de que el agente de no-mistakes esté operativo headless (claude autenticado, o
glm enrutado sin colgar el daemon), que es un detalle del propio no-mistakes. Para una integración
**determinista pura sin agente**, el camino 2 es preferible.

## Alcance / limitaciones
- `nm_gate.py` corre los chequeos **project-wide** (no por-diff). Gatear los task-contracts
  *afectados* por el cambio (como hace `integrations/github/ci_gate.py` con descubrimiento por diff)
  es una mejora futura.
- **Camino 2 (recomendado para robustez, requiere PR en Go a no-mistakes):** un `Step` de primera
  clase que corra ccdd-gate y emita findings deterministas **sin agente**, ubicado antes de `push`.
  Evita la dependencia del agente headless y el probe del daemon.
- No se incluye correr la suite de tests del repo; encadenala en el comando si la querés
  (`... && python -m pytest`).
