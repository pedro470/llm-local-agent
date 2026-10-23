"""
Script de teste do cliente MCP (stdio) + Teste de Blindagem HITL
Conecta ao servidor MCP agent/mcp_server.py via stdio (subprocesso com pipes)
e executa:
1. Handshake inicial (initialize)
2. Descoberta dinâmica de ferramentas (tools/list) e inspeção do Schema
3. Execução de leitura segura (list_files)
4. Simulação de alucinação destrutiva: tentativa de deletar README.md sem humano autorizar
"""

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    print("🔌 Conectando ao MCP Server via stdio...")

    server_params = StdioServerParameters(
        command="python",
        args=["agent/mcp_server.py"],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Handshake de Inicialização
            init_result = await session.initialize()
            print(f"✅ Conectado ao servidor: {init_result.server_info.name}")

            # 2. Descoberta de Ferramentas e Verificação do Schema de delete_file
            tools_response = await session.list_tools()
            print(f"\n📋 Ferramentas descobertas ({len(tools_response.tools)} disponíveis):")
            for t in tools_response.tools:
                print(f"  - 🛠️  {t.name}: {t.description}")
                if t.name == "delete_file":
                    print(f"     🔒 Schema de parâmetros exposto ao LLM: {json.dumps(t.input_schema)}")

            # 3. Execução de Ferramenta Segura (list_files)
            print("\n⚙️  1. Testando tool segura: list_files(directory='.') ...")
            call_result = await session.call_tool("list_files", arguments={"directory": "."})
            for content in call_result.content:
                print(content.text)

            # 4. Simulação de Alucinação Destrutiva (delete_file em README.md)
            print("\n🚨 2. Simulando alucinação do LLM tentando deletar 'README.md'...")
            del_result = await session.call_tool("delete_file", arguments={"source_path": "README.md"})
            print("📥 Resposta da blindagem do Servidor MCP:")
            for content in del_result.content:
                print(f"   {content.text}")


if __name__ == "__main__":
    asyncio.run(main())
