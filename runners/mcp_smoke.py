"""mcp_smoke.py — cliente de humo: arranca complexity_mcp.py y ejerce el protocolo MCP real
(initialize -> tools/list -> tools/call x3) por stdio JSON-RPC. Verifica el servidor end-to-end."""
import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SERVER = Path(__file__).resolve().parent / "complexity_mcp.py"

COMPLEX = '''def procesar(c, l, d, m, p, a, k, u, r):
    t = 0
    for x in l:
        if x > 0:
            if c == "a":
                if p:
                    if k and u:
                        t += x
                    else:
                        t += x * 2
                else:
                    t += x * 3
            elif c == "b":
                t += x
        elif x == 0:
            continue
    return t
'''
SECRET = 'API_KEY = "sk-abc123456789012345678901"\ndef f():\n    return 1\n'


def main():
    proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, encoding="utf-8", bufsize=1)

    def rpc(mid, method, params=None):
        req = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            req["params"] = params
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    init = rpc(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    print("initialize ->", init["result"]["serverInfo"])

    tl = rpc(2, "tools/list")
    print("tools/list ->", [t["name"] for t in tl["result"]["tools"]])

    r = rpc(3, "tools/call", {"name": "measure_complexity", "arguments": {"code": COMPLEX}})
    m = json.loads(r["result"]["content"][0]["text"])
    print("measure_complexity ->")
    for f in m["findings"]:
        flag = "  ⚠ supera umbral" if f.get("exceeds_threshold") else ""
        print(f"   {f['function']:10} {f['metric']:16} = {f['value']:>3} (umbral {f['threshold']}){flag}")

    r = rpc(4, "tools/call", {"name": "complexity_rubric", "arguments": {"agent": "complexity-agent"}})
    rub = json.loads(r["result"]["content"][0]["text"])
    print(f"complexity_rubric -> agent={rub['agent']} system={len(rub['system'])}c "
          f"policies={len(rub['policies'])}c thresholds={len(rub['thresholds'])}c")

    r = rpc(5, "tools/call", {"name": "scan_guardrails", "arguments": {"code": SECRET}})
    g = json.loads(r["result"]["content"][0]["text"])
    print("scan_guardrails (con secreto) ->", "blocked" if g["blocked"] else "ok",
          [f"{x['id']}={'X' if x['fired'] else 'ok'}" for x in g["guardrails"]])

    proc.stdin.close()
    proc.wait(timeout=5)
    print("\nOK — el servidor MCP responde el protocolo y las 3 tools funcionan.")


if __name__ == "__main__":
    main()
