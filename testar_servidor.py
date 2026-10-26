"""
Testa o servidor MCP sem usar o Gemini.

    python testar_servidor.py                                   (local)
    python testar_servidor.py https://SEU-SERVICO.onrender.com/mcp   (hospedado)
"""

import asyncio
import json
import sys

from fastmcp import Client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"


async def main():
    print(f"Conectando em {URL} (no Render grátis pode levar ~1 min para acordar)")
    async with Client(URL, timeout=120, init_timeout=120) as mcp:
        ferramentas = await mcp.list_tools()
        print(f"\n{len(ferramentas)} ferramentas: {[f.name for f in ferramentas]}")

        testes = [
            ("ler_regras_contrato", {"secao": "Canais"}),
            ("ler_ficha_agente", {"numero_agente": 2}),
            ("ler_briefing", {"id_execucao": "EXEMPLO"}),
            ("validar_canais", {"canais": ["Instagram", "Orkut"]}),
            ("calcular_distribuicao_orcamento",
             {"orcamento_total": 100000,
              "percentuais_por_canal": {"Instagram": 40, "Google Pesquisa": 35, "TikTok": 25}}),
            ("calcular_indicadores",
             {"investimento": 100000, "receita": 320000, "margem_contribuicao_percentual": 40}),
            ("simular_canais", {"canais": ["Instagram", "TikTok"], "investimento_por_canal": 1000}),
            ("validar_execucao", {"id_execucao": "EXEMPLO"}),
        ]
        for nome, args in testes:
            r = await mcp.call_tool(nome, args, raise_on_error=False)
            dados = r.structured_content if r.structured_content is not None else r.content[0].text
            print(f"\n{nome}: {json.dumps(dados, ensure_ascii=False)[:300]}")

    print("\nTudo certo: o servidor está respondendo.")


if __name__ == "__main__":
    asyncio.run(main())
