import json
import urllib.request
import re
import sys
import subprocess
from pathlib import Path

def main():
    print("=== SMALL EXECUTOR (LM Studio Gemma4) ===")
    task_file = Path("examples/sandbox/task.md")
    target_file = Path("examples/sandbox/disassembler.py")
    
    task_content = task_file.read_text(encoding="utf-8")
    source_code = target_file.read_text(encoding="utf-8")
    
    prompt = f"""Eres un agente implementador "Small Executor".
Tu objetivo es resolver el siguiente Task Contract refactorizando la función especificada para cumplir con los topes de complejidad ciclomática.
Debes devolver el archivo fuente COMPLETO y REFACTORIZADO. No modifiques la firma externa.

### TASK CONTRACT:
{task_content}

### CÓDIGO FUENTE ACTUAL ({target_file}):
```python
{source_code}
```

REGLAS DE SALIDA:
- Devuelve SOLO el código completo de la función refactorizada (todo el contenido del archivo) dentro de un bloque ```python ... ```.
- No agregues explicaciones.
- Se recomienda usar una estructura de datos (ej. un diccionario) en lugar de múltiples sentencias if/elif anidadas.
"""

    data = json.dumps({
        "model": "gemma-4-12b-coder",
        "messages": [
            {"role": "system", "content": "Eres un experto en refactorización orientada a métricas (cyclomatic complexity)."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 2000
    }).encode("utf-8")
    
    req = urllib.request.Request("http://localhost:1234/v1/chat/completions", data=data, headers={"Content-Type": "application/json"})
    
    print("Enviando prompt a LM Studio (http://localhost:1234/v1)...")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            answer = res_json["choices"][0]["message"]["content"]
    except Exception as e:
        print("Error conectando a LM Studio:", e)
        return
        
    code_match = re.search(r"```python(.*?)```", answer, re.DOTALL)
    if not code_match:
        code_match = re.search(r"```(.*?)```", answer, re.DOTALL)
        
    if code_match:
        new_code = code_match.group(1).strip()
    else:
        new_code = answer.strip()
        
    print(f"Respuesta recibida ({len(new_code)} bytes). Aplicando cambios...")
    
    # Aplicar cambios
    target_file.write_text(new_code, encoding="utf-8")
    
    print("\nEjecutando CCDD Gate (task_gate.py)...")
    result = subprocess.run([sys.executable, "runners/task_gate.py", "examples/sandbox/task.md"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode == 0:
        print("¡Misión Cumplida! El modelo refactorizó el código y el Gate de Complejidad lo aprobó determinísticamente.")
    else:
        print("El modelo falló el Gate. Revisa la salida.")

if __name__ == "__main__":
    main()
