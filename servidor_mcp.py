"""
Servidor MCP — Marketing Campaign Commander (versão hospedada)
==============================================================

Caixa de ferramentas central do sistema multiagente. Qualquer agente que se
conecta pelo link recebe a lista de ferramentas e as regras do contrato.

Funciona de dois jeitos, com o mesmo código:
- Hospedado (Render): o Render define a variável PORT e roda
  `python servidor_mcp.py`. Link: https://<seu-servico>.onrender.com/mcp
- Local (teste no PC): `python servidor_mcp.py` -> http://localhost:8000/mcp

Mesa compartilhada: as saídas dos agentes ficam em armazenamento/<id_execucao>/.
No plano grátis do Render essa pasta é apagada quando o servidor dorme ou
reinicia, por isso cada agente também guarda uma cópia local (registro oficial).
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

BASE = Path(__file__).resolve().parent
PASTA_REGRAS = BASE / "regras"
PASTA_DADOS = BASE / "dados"
PASTA_EXEMPLOS = BASE / "exemplos"        # fixos no GitHub (id EXEMPLO)
PASTA_ARMAZENAMENTO = BASE / "armazenamento"  # mesa compartilhada (temporária)

ID_EXEMPLO = "EXEMPLO"

CANAIS_SUPORTADOS = [
    "Instagram", "Facebook", "Google Pesquisa", "YouTube",
    "TikTok", "LinkedIn", "E-mail Marketing", "Influenciadores",
]

OBJETIVOS_VALIDOS = ["vendas", "leads", "reconhecimento"]

AGENTES = {
    1: {"nome": "Público", "chave": "agente01_publico", "grupo": "3",
        "script": "GRUPO_3/agente01_publico.py", "le": ["briefing"],
        "entrega_para": "agente02_concorrencia",
        "missao": "Definir QUEM é o cliente: público prioritário, dores e motivações."},
    2: {"nome": "Concorrência", "chave": "agente02_concorrencia", "grupo": "1",
        "script": "GRUPO_1/agente02_concorrencia.py",
        "le": ["briefing", "saída 01", "dados concorrentes"],
        "entrega_para": "agente03_canais",
        "missao": "Mostrar COMO está o mercado: concorrentes, lacunas e diferenciais."},
    3: {"nome": "Canais", "chave": "agente03_canais", "grupo": "1",
        "script": "GRUPO_1/agente03_canais.py",
        "le": ["briefing", "saídas 01 e 02"],
        "entrega_para": "agente04_criativo",
        "missao": "Escolher ONDE anunciar, só com canais da lista fechada."},
    4: {"nome": "Criativo", "chave": "agente04_criativo", "grupo": "3",
        "script": "GRUPO_3/agente04_criativo.py",
        "le": ["briefing", "saídas 01, 02 e 03"],
        "entrega_para": "agente05_performance",
        "missao": "Definir O QUE dizer: conceito e mensagem para cada canal escolhido."},
    5: {"nome": "Simulador de Performance", "chave": "agente05_performance", "grupo": "2",
        "script": "GRUPO_2/agente05_performance.py",
        "le": ["briefing", "saídas 03 e 04", "dados premissas_simulacao"],
        "entrega_para": "agente06_financeiro",
        "missao": "Projetar QUANTO cada canal tende a render, em 3 cenários (simulação)."},
    6: {"nome": "Financeiro", "chave": "agente06_financeiro", "grupo": "2",
        "script": "GRUPO_2/agente06_financeiro.py",
        "le": ["briefing", "saídas 03 e 05"],
        "entrega_para": "orquestrador",
        "missao": "Distribuir o orçamento por canal (soma exata) e calcular ROAS/ROI."},
}

CAMPOS_MENSAGEM = {
    "id_execucao": str, "agente_origem": str, "agente_destino": str,
    "data_hora": str, "status": str, "entradas_usadas": list, "dados": dict,
    "premissas": list, "erros": list, "observacoes": str,
}

ARQUIVOS_DADOS = {
    "concorrentes": "concorrentes.json",
    "premissas_simulacao": "premissas_simulacao.json",
}

INSTRUCOES = """Servidor do sistema multiagente Marketing Campaign Commander
(simulador de planejamento de campanha de marketing com R$ 100 mil).
Antes de trabalhar, todo agente deve chamar ler_regras_contrato e
ler_ficha_agente com o seu número. Contas são sempre feitas pelas ferramentas
de cálculo, nunca pelo modelo. Todos os dados são fictícios."""

mcp = FastMCP("marketing-campaign-commander", instructions=INSTRUCOES)


# ------------------------------------------------------------- auxiliares ---

def _ler_json(caminho: Path) -> dict | None:
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def _id_valido(id_execucao: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,60}", id_execucao or ""))


def _arquivo_saida(numero_agente: int) -> str:
    return f"{AGENTES[numero_agente]['chave']}_saida.json"


def _problemas_briefing(b: dict) -> list[str]:
    problemas = []
    for campo in ["empresa", "produto_ou_servico", "objetivo_campanha",
                  "orcamento_total", "duracao_dias"]:
        if b.get(campo) in (None, "", 0):
            problemas.append(f"Campo obrigatório ausente: {campo}")
    if b.get("objetivo_campanha") and b["objetivo_campanha"] not in OBJETIVOS_VALIDOS:
        problemas.append(f"objetivo_campanha deve ser um de {OBJETIVOS_VALIDOS}")
    orc = b.get("orcamento_total")
    if orc not in (None, "") and (not isinstance(orc, (int, float)) or orc <= 0):
        problemas.append("orcamento_total deve ser um número maior que zero")
    if b.get("objetivo_campanha") == "vendas" and not b.get("ticket_medio"):
        problemas.append("ticket_medio é obrigatório quando o objetivo é vendas")
    return problemas


def _problemas_mensagem(mensagem: dict, numero_agente: int) -> list[str]:
    problemas = []
    for campo, tipo in CAMPOS_MENSAGEM.items():
        if campo not in mensagem:
            problemas.append(f"Campo ausente: {campo}")
        elif not isinstance(mensagem[campo], tipo):
            problemas.append(f"Campo {campo} deve ser {tipo.__name__}")
    extras = set(mensagem) - set(CAMPOS_MENSAGEM)
    if extras:
        problemas.append(f"Campos fora do padrão: {sorted(extras)}")
    if mensagem.get("status") not in ("sucesso", "erro"):
        problemas.append('status deve ser "sucesso" ou "erro"')
    if mensagem.get("status") == "erro" and not mensagem.get("erros"):
        problemas.append('status "erro" exige o motivo na lista erros')
    esperado = AGENTES[numero_agente]["chave"]
    if mensagem.get("agente_origem") != esperado:
        problemas.append(f"agente_origem deve ser {esperado} (cada agente só grava a própria saída)")
    return problemas


# ---------------------------------------------------------------- regras ---

@mcp.tool
def ler_regras_contrato(secao: str | None = None) -> dict:
    """Retorna as regras do Contrato Base dos Agentes. Todo agente deve ler
    antes de trabalhar. Sem 'secao', retorna tudo. Com 'secao', retorna só a
    seção cujo título contém o texto (ex.: 'Canais', 'Formato', 'dados')."""
    texto = (PASTA_REGRAS / "contrato.md").read_text(encoding="utf-8")
    partes = re.split(r"\n(?=## )", texto)
    titulos = [p.splitlines()[0].removeprefix("## ").strip()
               for p in partes if p.startswith("## ")]
    if not secao:
        return {"secoes": titulos, "conteudo": texto}
    achadas = [p for p in partes if p.startswith("## ")
               and secao.lower() in p.splitlines()[0].lower()]
    if not achadas:
        return {"erro": f"Seção não encontrada. Seções: {titulos}"}
    return {"conteudo": "\n\n".join(achadas)}


@mcp.tool
def ler_ficha_agente(numero_agente: int) -> dict:
    """Retorna a ficha de um agente (1 a 6): nome, grupo, missão, o que lê,
    para quem entrega e o nome do arquivo de saída."""
    if numero_agente not in AGENTES:
        return {"erro": "numero_agente deve ser de 1 a 6"}
    ficha = dict(AGENTES[numero_agente])
    ficha["numero"] = numero_agente
    ficha["arquivo_saida"] = _arquivo_saida(numero_agente)
    ficha["formato_saida"] = list(CAMPOS_MENSAGEM)
    return ficha


@mcp.tool
def listar_canais_suportados() -> list[str]:
    """Lista fechada de canais. Nenhum agente pode sugerir canal fora desta
    lista, e os nomes devem ser escritos exatamente assim."""
    return CANAIS_SUPORTADOS


# -------------------------------------------------- mesa compartilhada ---

@mcp.tool
def registrar_briefing(briefing: dict, id_execucao: str | None = None) -> dict:
    """[Uso do Orquestrador] Valida o briefing e abre uma nova execução.
    Se o id_execucao não for informado, cria um (EXEC-AAAAMMDD-HHMMSS).
    Retorna o id_execucao para repassar a todos os agentes."""
    problemas = _problemas_briefing(briefing)
    if problemas:
        return {"registrado": False, "problemas": problemas}
    id_execucao = id_execucao or datetime.now().strftime("EXEC-%Y%m%d-%H%M%S")
    if not _id_valido(id_execucao):
        return {"registrado": False, "problemas": ["id_execucao inválido"]}
    pasta = PASTA_ARMAZENAMENTO / id_execucao
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "briefing.json").write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"registrado": True, "id_execucao": id_execucao}


@mcp.tool
def ler_briefing(id_execucao: str = ID_EXEMPLO) -> dict:
    """Retorna o briefing da campanha de uma execução: empresa, produto,
    objetivo, orçamento total, duração, região, ticket médio e margem.
    Use id_execucao 'EXEMPLO' para testar com o briefing de exemplo."""
    if not _id_valido(id_execucao):
        return {"erro": "id_execucao inválido"}
    b = _ler_json(PASTA_ARMAZENAMENTO / id_execucao / "briefing.json")
    if b is None and id_execucao == ID_EXEMPLO:
        b = _ler_json(PASTA_EXEMPLOS / "briefing.json")
    if b is None:
        return {"erro": f"Nenhum briefing registrado para {id_execucao}. "
                        "O Orquestrador precisa chamar registrar_briefing primeiro."}
    return b


@mcp.tool
def gravar_saida(id_execucao: str, numero_agente: int, mensagem: dict) -> dict:
    """[Uso do script do agente, não do modelo] Grava a saída de um agente
    no formato padrão do contrato, depois de conferir todos os campos."""
    if not _id_valido(id_execucao):
        return {"gravado": False, "problemas": ["id_execucao inválido"]}
    if numero_agente not in AGENTES:
        return {"gravado": False, "problemas": ["numero_agente deve ser de 1 a 6"]}
    problemas = _problemas_mensagem(mensagem, numero_agente)
    if mensagem.get("id_execucao") != id_execucao:
        problemas.append("id_execucao da mensagem diferente do informado")
    if problemas:
        return {"gravado": False, "problemas": problemas}
    pasta = PASTA_ARMAZENAMENTO / id_execucao
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / _arquivo_saida(numero_agente)).write_text(
        json.dumps(mensagem, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"gravado": True, "arquivo": f"{id_execucao}/{_arquivo_saida(numero_agente)}"}


@mcp.tool
def ler_saida_agente(numero_agente: int, id_execucao: str = ID_EXEMPLO) -> dict:
    """Retorna a saída já gravada por um agente (1 Público, 2 Concorrência,
    3 Canais, 4 Criativo, 5 Simulador de Performance, 6 Financeiro) numa
    execução. Com id 'EXEMPLO', usa as saídas de exemplo do projeto."""
    if numero_agente not in AGENTES:
        return {"erro": "numero_agente deve ser de 1 a 6"}
    if not _id_valido(id_execucao):
        return {"erro": "id_execucao inválido"}
    nome = _arquivo_saida(numero_agente)
    s = _ler_json(PASTA_ARMAZENAMENTO / id_execucao / nome)
    if s is None and id_execucao == ID_EXEMPLO:
        s = _ler_json(PASTA_EXEMPLOS / nome)
    if s is None:
        return {"erro": f"O agente {numero_agente:02d} ainda não gravou saída em {id_execucao}"}
    return s


@mcp.tool
def listar_execucoes() -> list[dict]:
    """Lista as execuções guardadas no servidor e quais agentes já gravaram
    saída em cada uma."""
    if not PASTA_ARMAZENAMENTO.exists():
        return []
    resultado = []
    for pasta in sorted(PASTA_ARMAZENAMENTO.iterdir()):
        if pasta.is_dir():
            feitos = [n for n in AGENTES if (pasta / _arquivo_saida(n)).exists()]
            resultado.append({"id_execucao": pasta.name,
                              "tem_briefing": (pasta / "briefing.json").exists(),
                              "agentes_concluidos": feitos})
    return resultado


@mcp.tool
def ler_dados(nome: str) -> dict:
    """Retorna uma base fictícia: 'concorrentes' (Grupo 1) ou
    'premissas_simulacao' (Grupo 2). Todos os dados são simulados."""
    if nome not in ARQUIVOS_DADOS:
        return {"erro": f"nome deve ser um de {list(ARQUIVOS_DADOS)}"}
    d = _ler_json(PASTA_DADOS / ARQUIVOS_DADOS[nome])
    return d if d is not None else {"erro": f"Base {nome} ainda não foi publicada"}


# ------------------------------------------------------------- validação ---

@mcp.tool
def validar_briefing(briefing: dict) -> dict:
    """Confere campos obrigatórios, objetivo, orçamento e ticket médio.
    Retorna {'valido': bool, 'problemas': [...]}."""
    problemas = _problemas_briefing(briefing)
    return {"valido": not problemas, "problemas": problemas}


@mcp.tool
def validar_canais(canais: list[str]) -> dict:
    """Confere se todos os canais estão na lista fechada."""
    invalidos = [c for c in canais if c not in CANAIS_SUPORTADOS]
    return {"valido": not invalidos, "canais_invalidos": invalidos}


@mcp.tool
def verificar_saida(numero_agente: int, mensagem: dict) -> dict:
    """Confere se uma mensagem segue o formato padrão do contrato, sem gravar.
    Útil para os grupos testarem antes de entregar."""
    if numero_agente not in AGENTES:
        return {"valido": False, "problemas": ["numero_agente deve ser de 1 a 6"]}
    problemas = _problemas_mensagem(mensagem, numero_agente)
    return {"valido": not problemas, "problemas": problemas}


# ---------------------------------------------------------------- cálculo ---

@mcp.tool
def calcular_distribuicao_orcamento(orcamento_total: float,
                                    percentuais_por_canal: dict[str, float]) -> dict:
    """Converte percentuais por canal em reais. Os percentuais devem somar 100
    e a soma dos valores fecha exatamente com o orçamento (centavos de
    arredondamento vão para o maior canal).
    Exemplo: orcamento_total=100000, percentuais_por_canal={"Instagram": 40,
    "Google Pesquisa": 35, "TikTok": 25}"""
    if orcamento_total <= 0:
        return {"erro": "orcamento_total deve ser maior que zero"}
    invalidos = [c for c in percentuais_por_canal if c not in CANAIS_SUPORTADOS]
    if invalidos:
        return {"erro": f"Canais fora da lista suportada: {invalidos}"}
    soma_pct = round(sum(percentuais_por_canal.values()), 4)
    if soma_pct != 100:
        return {"erro": f"Os percentuais somam {soma_pct}, devem somar 100"}

    total_centavos = round(orcamento_total * 100)
    valores = {c: int(total_centavos * p / 100) for c, p in percentuais_por_canal.items()}
    maior = max(percentuais_por_canal, key=percentuais_por_canal.get)
    valores[maior] += total_centavos - sum(valores.values())
    return {
        "orcamento_total": orcamento_total,
        "distribuicao": {c: v / 100 for c, v in valores.items()},
        "soma_confere": sum(valores.values()) == total_centavos,
    }


@mcp.tool
def calcular_indicadores(investimento: float, receita: float,
                         margem_contribuicao_percentual: float | None = None) -> dict:
    """Calcula ROAS e, se houver margem, ROI. Receita não é lucro e ROAS não
    é ROI. ROAS = receita / investimento.
    ROI = (receita x margem - investimento) / investimento."""
    if investimento <= 0:
        return {"erro": "investimento deve ser maior que zero"}
    r = {"roas": round(receita / investimento, 2), "roi_percentual": None}
    if margem_contribuicao_percentual is not None:
        lucro_bruto = receita * margem_contribuicao_percentual / 100
        r["roi_percentual"] = round((lucro_bruto - investimento) / investimento * 100, 2)
    else:
        r["observacao"] = "Sem margem no briefing: ROI não calculado"
    return r


# ------------------------------------------------------------ página raiz ---

@mcp.custom_route("/", methods=["GET"])
async def pagina_inicial(request: Request) -> JSONResponse:
    """Abrir o link no navegador mostra que o servidor está no ar
    (e acorda o servidor no plano grátis do Render)."""
    return JSONResponse({
        "servidor": "Marketing Campaign Commander — MCP",
        "status": "no ar",
        "endpoint_mcp": "/mcp",
    })


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 8000))
    mcp.run(transport="http", host="0.0.0.0", port=porta, show_banner=False)
