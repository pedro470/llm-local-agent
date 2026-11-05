"""Checagem manual do servidor MCP de delegação, pelo protocolo de verdade (stdio), como um cliente faria.

    .venv/Scripts/python tools/test_delegar_mcp_client.py            # lista ferramentas e modelos
    .venv/Scripts/python tools/test_delegar_mcp_client.py SPEC.md "COMANDO DE VERIFICAÇÃO"
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


def text(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    params = StdioServerParameters(command=str(ROOT / ".venv/Scripts/python.exe"),
                                   args=[str(ROOT / "tools/delegar_mcp.py")], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            print("servidor:", init.server_info.name)
            print("ferramentas:", [t.name for t in (await s.list_tools()).tools])
            print(text(await s.call_tool("modelos", {})))
            if len(sys.argv) < 2:
                return
            spec = Path(sys.argv[1]).read_text(encoding="utf-8")
            args = {"especificacao": spec, "pasta": str(ROOT), "titulo": "teste-mcp"}
            if len(sys.argv) > 2:
                args["verificacao"] = sys.argv[2]
            out = text(await s.call_tool("delegar", args))
            print(out)
            job = out.split()[1]
            while True:
                st = text(await s.call_tool("status", {"job_id": job, "aguardar_segundos": 60}))
                print("·", st.splitlines()[0])
                if "estado: concluido" in st or "estado: erro" in st:
                    print(st)
                    return


if __name__ == "__main__":
    asyncio.run(main())
