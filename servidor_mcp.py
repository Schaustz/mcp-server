"""
Servidor MCP — Marketing Campaign Commander
===========================================

Caixa de ferramentas central do sistema multiagente. Qualquer agente que se
conecta pelo link recebe a lista de ferramentas, as regras do contrato e a
ficha do seu papel (incluindo o formato exato da saída).

Funciona de dois jeitos, com o mesmo código:
- Hospedado (Render): o Render define a variável PORT e roda
  `python servidor_mcp.py`. Link: https://<seu-servico>.onrender.com/mcp
- Local (teste no PC): `python servidor_mcp.py` -> http://localhost:8000/mcp

Mesa compartilhada: as saídas dos agentes ficam em armazenamento/<id_execucao>/.
No plano grátis do Render essa pasta é apagada quando o servidor dorme ou
reinicia. Os exemplos oficiais (id EXEMPLO) ficam fixos em exemplos/.

Ferramentas por agente
- Todos:       ler_regras_contrato, ler_ficha_agente, listar_canais_suportados,
               ler_briefing, ler_saida_agente, verificar_saida
- 01 Público:  (usa as de todos)
- 02 Concorr.: buscar_concorrentes_web (internet, Tavily), ler_historico_concorrentes
               (base de reais no GitHub), ler_concorrentes (reserva fictícia)
- 03 Canais:   validar_canais, ler_premissas_simulacao (custos de referência)
- 04 Criativo: verificar_mensagens_criativo
- 05 Simul.:   ler_premissas_simulacao, simular_canais
- 06 Financ.:  validar_distribuicao, calcular_distribuicao_orcamento,
               projetar_resultados, calcular_indicadores
- Orquestr.:   registrar_briefing, validar_briefing, listar_execucoes,
               validar_execucao, gravar_saida (usada pelo script de cada agente)
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from html import escape

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

BASE = Path(__file__).resolve().parent
PASTA_REGRAS = BASE / "regras"
PASTA_DADOS = BASE / "dados"
PASTA_EXEMPLOS = BASE / "exemplos"            # fixos no GitHub (id EXEMPLO)
PASTA_ARMAZENAMENTO = BASE / "armazenamento"  # mesa compartilhada (temporária)

ID_EXEMPLO = "EXEMPLO"

CANAIS_SUPORTADOS = [
    "Instagram", "Facebook", "Google Pesquisa", "YouTube",
    "TikTok", "LinkedIn", "E-mail Marketing", "Influenciadores",
]
OBJETIVOS_VALIDOS = ["vendas", "leads", "reconhecimento"]
CENARIOS = ["pessimista", "realista", "otimista"]

# Limites de referência de texto por canal (usados pelo Criativo)
LIMITES_TEXTO = {
    "Google Pesquisa": {"titulo": 30, "texto": 90},
    "Instagram": {"texto": 2200},
    "Facebook": {"texto": 2200},
    "TikTok": {"texto": 2200},
    "YouTube": {"titulo": 100, "texto": 5000},
    "LinkedIn": {"texto": 3000},
    "E-mail Marketing": {"titulo": 60},
    "Influenciadores": {"texto": 2200},
}

# ------------------------------------------------------- fichas dos agentes ---
# formato_dados é o modelo do campo "dados" que cada agente entrega.
# Os grupos podem enriquecer, mas os campos obrigatórios não podem faltar.

AGENTES = {
    1: {
        "nome": "Público", "chave": "agente01_publico", "grupo": "3",
        "script": "GRUPO_3/agente01_publico.py",
        "le": ["briefing"],
        "entrega_para": "agente02_concorrencia",
        "missao": "Definir QUEM é o cliente: público prioritário, públicos secundários, dores e motivações.",
        "ferramentas_recomendadas": ["ler_briefing"],
        "campos_obrigatorios": ["publico_prioritario", "publicos_secundarios", "insights"],
        "formato_dados": {
            "publico_prioritario": {
                "nome": "", "descricao": "", "faixa_etaria": "", "genero_predominante": "",
                "regiao": "", "interesses": [""], "dores": [""], "motivacoes": [""],
                "comportamento_digital": "",
            },
            "publicos_secundarios": [{"nome": "", "descricao": "", "por_que_importa": ""}],
            "insights": [""],
        },
    },
    2: {
        "nome": "Concorrência", "chave": "agente02_concorrencia", "grupo": "1",
        "script": "GRUPO_1/agente02_concorrencia.py",
        "le": ["briefing", "saída 01", "busca de concorrentes na internet"],
        "entrega_para": "agente03_canais",
        "missao": ("Mostrar COMO está o mercado: concorrentes, lacunas e diferenciais. "
                   "Os concorrentes vêm da internet (buscar_concorrentes_web), com o link "
                   "da fonte; a base fictícia (ler_concorrentes) é só a reserva."),
        "ferramentas_recomendadas": ["ler_briefing", "ler_saida_agente", "buscar_concorrentes_web",
                                     "ler_historico_concorrentes", "ler_concorrentes"],
        "campos_obrigatorios": ["concorrentes_analisados", "lacunas_de_mercado",
                                "diferenciais_sugeridos", "canais_mais_disputados"],
        "formato_dados": {
            "concorrentes_analisados": [{"nome": "", "tipo": "real | simulado",
                                         "fonte": "link de buscar_concorrentes_web (obrigatório se real)",
                                         "posicionamento": "",
                                         "ameaca": "alta | media | baixa", "justificativa": ""}],
            "lacunas_de_mercado": [""],
            "diferenciais_sugeridos": [""],
            "canais_mais_disputados": [""],
        },
    },
    3: {
        "nome": "Canais", "chave": "agente03_canais", "grupo": "1",
        "script": "GRUPO_1/agente03_canais.py",
        "le": ["briefing", "saídas 01 e 02"],
        "entrega_para": "agente04_criativo",
        "missao": "Escolher ONDE anunciar (2 a 5 canais), só com canais da lista fechada.",
        "ferramentas_recomendadas": ["ler_briefing", "ler_saida_agente", "listar_canais_suportados",
                                     "ler_premissas_simulacao", "validar_canais"],
        "campos_obrigatorios": ["canais_escolhidos", "canais_descartados"],
        "formato_dados": {
            "canais_escolhidos": [{"canal": "", "prioridade": 1, "papel": "", "justificativa": ""}],
            "canais_descartados": [{"canal": "", "motivo": ""}],
        },
    },
    4: {
        "nome": "Criativo", "chave": "agente04_criativo", "grupo": "3",
        "script": "GRUPO_3/agente04_criativo.py",
        "le": ["briefing", "saídas 01, 02 e 03"],
        "entrega_para": "agente05_performance",
        "missao": "Definir O QUE dizer: conceito criativo e uma mensagem para cada canal escolhido.",
        "ferramentas_recomendadas": ["ler_briefing", "ler_saida_agente", "verificar_mensagens_criativo"],
        "campos_obrigatorios": ["conceito_criativo", "mensagens_por_canal"],
        "formato_dados": {
            "conceito_criativo": {"nome": "", "ideia_central": "", "tom_de_voz": ""},
            "mensagens_por_canal": [{"canal": "", "formato": "", "titulo": "", "texto": "",
                                     "chamada_para_acao": ""}],
        },
    },
    5: {
        "nome": "Simulador de Performance", "chave": "agente05_performance", "grupo": "2",
        "script": "GRUPO_2/agente05_performance.py",
        "le": ["briefing", "saídas 03 e 04", "dados premissas_simulacao"],
        "entrega_para": "agente06_financeiro",
        "missao": ("Projetar QUANTO cada canal escolhido tende a render a cada R$ 1.000 "
                   "investidos, nos 3 cenários. Os números vêm da ferramenta simular_canais; "
                   "o agente interpreta e ranqueia, nunca calcula. Passe SEMPRE o id_execucao "
                   "da execução atual em simular_canais (o ticket médio vem do briefing dela)."),
        "ferramentas_recomendadas": ["ler_briefing", "ler_saida_agente",
                                     "ler_premissas_simulacao", "simular_canais"],
        "campos_obrigatorios": ["base_simulacao", "resultados_por_canal", "ranking_eficiencia", "leitura"],
        "formato_dados": {
            "base_simulacao": "por R$ 1.000 investidos em cada canal",
            "resultados_por_canal": "copiar exatamente o resultados_por_canal de simular_canais",
            "ranking_eficiencia": [{"posicao": 1, "canal": "", "motivo": ""}],
            "leitura": [""],
        },
    },
    6: {
        "nome": "Financeiro", "chave": "agente06_financeiro", "grupo": "2",
        "script": "GRUPO_2/agente06_financeiro.py",
        "le": ["briefing", "saídas 03 e 05"],
        "entrega_para": "orquestrador",
        "missao": ("Distribuir o orçamento por canal (soma exata) e projetar receita, ROAS e ROI "
                   "nos 3 cenários. Percentuais vêm do agente; valores e KPIs vêm das ferramentas. "
                   "Passe SEMPRE o id_execucao da execução atual em projetar_resultados "
                   "(ticket médio e margem vêm do briefing dela)."),
        "ferramentas_recomendadas": ["ler_briefing", "ler_saida_agente", "validar_distribuicao",
                                     "calcular_distribuicao_orcamento", "projetar_resultados"],
        "campos_obrigatorios": ["distribuicao", "total_distribuido", "projecao", "justificativa"],
        "formato_dados": {
            "distribuicao": [{"canal": "", "percentual": 0, "valor": 0}],
            "total_distribuido": 0,
            "projecao": {"totais_por_cenario": "copiar exatamente de projetar_resultados "
                                               "(pessimista, realista e otimista)"},
            "justificativa": [""],
        },
    },
}

CAMPOS_MENSAGEM = {
    "id_execucao": str, "agente_origem": str, "agente_destino": str,
    "data_hora": str, "status": str, "entradas_usadas": list, "dados": dict,
    "premissas": list, "erros": list, "observacoes": str,
}

INSTRUCOES = """Servidor do sistema multiagente Marketing Campaign Commander
(simulador de planejamento de campanha de marketing com R$ 100 mil).
Antes de trabalhar, todo agente deve chamar ler_regras_contrato e
ler_ficha_agente com o seu número; a ficha traz o formato exato da saída.
Contas são sempre feitas pelas ferramentas, nunca pelo modelo.
Premissas e números são simulados; concorrentes podem ser reais quando vierem
de buscar_concorrentes_web (com o link da fonte)."""

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


def _briefing(id_execucao: str) -> dict | None:
    if not _id_valido(id_execucao):
        return None
    if id_execucao == ID_EXEMPLO:
        return _ler_json(PASTA_EXEMPLOS / "briefing.json")
    return _ler_json(PASTA_ARMAZENAMENTO / id_execucao / "briefing.json")


def _saida(numero_agente: int, id_execucao: str) -> dict | None:
    """Com EXEMPLO lê sempre o exemplo oficial (testes nunca o substituem)."""
    if not _id_valido(id_execucao):
        return None
    nome = _arquivo_saida(numero_agente)
    if id_execucao == ID_EXEMPLO:
        return _ler_json(PASTA_EXEMPLOS / nome)
    return _ler_json(PASTA_ARMAZENAMENTO / id_execucao / nome)


def _premissas() -> dict:
    return _ler_json(PASTA_DADOS / "premissas_simulacao.json") or {}


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


def _canais_da_lista(itens: list, campo: str = "canal") -> list[str]:
    """Extrai os nomes de canal de uma lista de strings ou de dicts."""
    nomes = []
    for item in itens or []:
        nomes.append(item.get(campo, "") if isinstance(item, dict) else str(item))
    return nomes


def _perto(a, b, tolerancia_rel=0.01, tolerancia_abs=1.0) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= max(tolerancia_abs, abs(b) * tolerancia_rel)


def _conferir_numeros(rotulo: str, informado: dict, calculado: dict, campos: list[str]) -> list[str]:
    """Compara números que o agente copiou com o que a ferramenta calcula."""
    problemas = []
    for campo in campos:
        esperado = calculado.get(campo)
        if esperado is None:
            continue
        if not _perto(informado.get(campo), esperado):
            problemas.append(f"{rotulo}.{campo} = {informado.get(campo)}, a ferramenta calcula {esperado} "
                             "(copie os números da ferramenta, não calcule)")
    return problemas


def _problemas_dados(numero_agente: int, dados: dict, id_execucao: str = ID_EXEMPLO) -> list[str]:
    """Regras específicas do campo 'dados' de cada agente."""
    ficha = AGENTES[numero_agente]
    problemas = [f"dados.{c} ausente" for c in ficha["campos_obrigatorios"] if c not in dados]
    if problemas:
        return problemas

    if numero_agente == 2:
        invalidos = [c for c in dados["canais_mais_disputados"] if c not in CANAIS_SUPORTADOS]
        if invalidos:
            problemas.append(f"canais_mais_disputados fora da lista: {invalidos}")
        for c in dados["concorrentes_analisados"]:
            if not isinstance(c, dict):
                continue
            tipo, fonte = c.get("tipo"), str(c.get("fonte") or "")
            if tipo not in ("real", "simulado"):
                problemas.append(f"concorrente {c.get('nome')}: \"tipo\" deve ser \"real\" "
                                 "(veio da internet) ou \"simulado\" (base fictícia)")
            elif tipo == "real" and not fonte.startswith("http"):
                problemas.append(f"concorrente {c.get('nome')}: tipo real precisa de \"fonte\" "
                                 "com o link vindo de buscar_concorrentes_web")
            elif tipo == "real" and not _url_buscada(fonte):
                problemas.append(f"concorrente {c.get('nome')}: a fonte {fonte} não apareceu em "
                                 "nenhuma busca de buscar_concorrentes_web; use só links "
                                 "devolvidos pela ferramenta")

    if numero_agente == 3:
        escolhidos = _canais_da_lista(dados["canais_escolhidos"])
        invalidos = [c for c in escolhidos if c not in CANAIS_SUPORTADOS]
        if invalidos:
            problemas.append(f"canais_escolhidos fora da lista: {invalidos}")
        regras = _premissas().get("regras_distribuicao", {})
        mn, mx = regras.get("minimo_canais", 2), regras.get("maximo_canais", 5)
        if not mn <= len(escolhidos) <= mx:
            problemas.append(f"escolha de {mn} a {mx} canais (veio {len(escolhidos)})")

    if numero_agente == 4:
        canais = _canais_da_lista(dados["mensagens_por_canal"])
        invalidos = [c for c in canais if c not in CANAIS_SUPORTADOS]
        if invalidos:
            problemas.append(f"mensagens_por_canal com canal fora da lista: {invalidos}")

    briefing = _briefing(id_execucao) or {}
    ticket = briefing.get("ticket_medio") or None
    campos_kpi = ["impressoes", "cliques", "engajamentos", "novos_seguidores", "conversoes", "receita"]

    if numero_agente == 5:
        res = dados["resultados_por_canal"]
        if not isinstance(res, dict) or not res:
            return ["resultados_por_canal deve ser o objeto devolvido por simular_canais"]
        for canal, cenarios in res.items():
            if canal not in CANAIS_SUPORTADOS:
                problemas.append(f"resultados_por_canal com canal fora da lista: {canal}")
                continue
            if not isinstance(cenarios, dict) or any(c not in cenarios for c in CENARIOS):
                problemas.append(f"{canal}: faltam os cenários {CENARIOS}")
                continue
            invest = cenarios["realista"].get("investimento", 1000)
            calc = _simular(canal, float(invest), ticket)
            for cen in CENARIOS:
                problemas += _conferir_numeros(f"{canal}.{cen}", cenarios[cen], calc[cen], campos_kpi)

    if numero_agente == 6:
        dist = dados["distribuicao"]
        if not isinstance(dist, list) or not dist:
            return ["distribuicao deve ser a lista devolvida por calcular_distribuicao_orcamento"]
        invalidos = [d.get("canal") for d in dist if d.get("canal") not in CANAIS_SUPORTADOS]
        if invalidos:
            problemas.append(f"distribuicao com canal fora da lista: {invalidos}")
        total = round(sum(float(d.get("valor", 0)) for d in dist), 2)
        if not _perto(dados.get("total_distribuido"), total, 0, 0.01):
            problemas.append("total_distribuido diferente da soma da distribuição")
        orc = briefing.get("orcamento_total")
        if orc and not _perto(total, orc, 0, 0.01):
            problemas.append(f"a distribuição soma {total}, mas o orçamento é {orc}")
        if orc:
            for d in dist:
                if not _perto(d.get("valor"), float(d.get("percentual", 0)) / 100 * orc, 0, 0.05):
                    problemas.append(f"{d.get('canal')}: valor não bate com o percentual "
                                     "(use calcular_distribuicao_orcamento)")
        proj = dados.get("projecao")
        totais = proj.get("totais_por_cenario") if isinstance(proj, dict) else None
        if not isinstance(totais, dict) or any(c not in totais for c in CENARIOS):
            problemas.append("projecao.totais_por_cenario deve ter os 3 cenários de projetar_resultados")
        elif not invalidos and briefing:
            calc = _projetar({d["canal"]: float(d["valor"]) for d in dist}, briefing)
            for cen in CENARIOS:
                problemas += _conferir_numeros(
                    f"projecao.{cen}", totais[cen], calc["totais_por_cenario"][cen],
                    ["investimento", "impressoes", "novos_seguidores", "conversoes", "receita", "roas"])

    if numero_agente in (5, 6) and problemas:
        ferramenta = "simular_canais" if numero_agente == 5 else "projetar_resultados"
        problemas.append(f"dica: chame {ferramenta} de novo com id_execucao=\"{id_execucao}\" "
                         "e copie o resultado sem mudar nada")
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
    if mensagem.get("status") == "sucesso" and isinstance(mensagem.get("dados"), dict):
        id_exec = mensagem.get("id_execucao")
        id_exec = id_exec if isinstance(id_exec, str) and _id_valido(id_exec) else ID_EXEMPLO
        problemas += _problemas_dados(numero_agente, mensagem["dados"], id_exec)
    return problemas


def _simular(canal: str, investimento: float, ticket_medio: float | None) -> dict:
    """Aplica as premissas a um canal nos 3 cenários. Só contas em Python."""
    prem = _premissas()
    p = prem["canais"][canal]
    resultado = {}
    for cenario in CENARIOS:
        m = prem["cenarios"][cenario]
        cpm = p["cpm"] * m["multiplicador_cpm"]
        tx = m["multiplicador_taxas"]
        impressoes = investimento / cpm * 1000
        cliques = impressoes * p["ctr_percentual"] / 100 * tx
        conversoes = cliques * p["taxa_conversao_percentual"] / 100 * tx
        engajamentos = impressoes * p["taxa_engajamento_percentual"] / 100 * tx
        seguidores = engajamentos * p["taxa_seguidor_percentual"] / 100 * tx
        r = {
            "investimento": round(investimento, 2),
            "impressoes": round(impressoes),
            "alcance": round(impressoes / p["frequencia_media"]),
            "cliques": round(cliques),
            "engajamentos": round(engajamentos),
            "novos_seguidores": round(seguidores),
            "conversoes": round(conversoes, 1),
            "cpc": round(investimento / cliques, 2) if cliques else None,
            "custo_por_seguidor": round(investimento / seguidores, 2) if seguidores >= 1 else None,
        }
        if ticket_medio:
            r["receita"] = round(conversoes * ticket_medio, 2)
        resultado[cenario] = r
    return resultado


# ---------------------------------------------------------------- regras ---

@mcp.tool
def ler_regras_contrato(secao: str | None = None) -> dict:
    """[Todos] Retorna as regras do Contrato Base dos Agentes. Todo agente deve
    ler antes de trabalhar. Sem 'secao', retorna tudo. Com 'secao', retorna só
    a seção cujo título contém o texto (ex.: 'Canais', 'Formato', 'dados')."""
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
    """[Todos] Retorna a ficha de um agente (1 a 6): missão, o que lê, para quem
    entrega, ferramentas recomendadas e o FORMATO EXATO do campo 'dados' da
    saída (formato_dados), com os campos obrigatórios."""
    if numero_agente not in AGENTES:
        return {"erro": "numero_agente deve ser de 1 a 6"}
    ficha = dict(AGENTES[numero_agente])
    ficha["numero"] = numero_agente
    ficha["arquivo_saida"] = _arquivo_saida(numero_agente)
    ficha["campos_da_mensagem"] = list(CAMPOS_MENSAGEM)
    return ficha


@mcp.tool
def listar_canais_suportados() -> list[str]:
    """[Todos] Lista fechada de canais. Nenhum agente pode sugerir canal fora
    desta lista, e os nomes devem ser escritos exatamente assim."""
    return CANAIS_SUPORTADOS


# -------------------------------------------------- mesa compartilhada ---

@mcp.tool
def registrar_briefing(briefing: dict, id_execucao: str | None = None) -> dict:
    """[Orquestrador] Valida o briefing e abre uma nova execução. Se o
    id_execucao não for informado, cria um (EXEC-AAAAMMDD-HHMMSS).
    Retorna o id_execucao para repassar a todos os agentes."""
    problemas = _problemas_briefing(briefing)
    if problemas:
        return {"registrado": False, "problemas": problemas}
    id_execucao = id_execucao or datetime.now().strftime("EXEC-%Y%m%d-%H%M%S")
    if not _id_valido(id_execucao) or id_execucao == ID_EXEMPLO:
        return {"registrado": False, "problemas": ["id_execucao inválido ou reservado"]}
    pasta = PASTA_ARMAZENAMENTO / id_execucao
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "briefing.json").write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"registrado": True, "id_execucao": id_execucao}


@mcp.tool
def ler_briefing(id_execucao: str = ID_EXEMPLO) -> dict:
    """[Todos] Retorna o briefing da campanha de uma execução: empresa,
    produto, objetivo, orçamento, duração, região, ticket médio e margem.
    Use id_execucao 'EXEMPLO' para o caso de exemplo oficial."""
    if not _id_valido(id_execucao):
        return {"erro": "id_execucao inválido"}
    b = _briefing(id_execucao)
    if b is None:
        return {"erro": f"Nenhum briefing registrado para {id_execucao}. "
                        "O Orquestrador precisa chamar registrar_briefing primeiro."}
    return b


@mcp.tool
async def gravar_saida(id_execucao: str, numero_agente: int, mensagem: dict) -> dict:
    """[Script do agente, não o modelo] Grava a saída de um agente no formato
    padrão do contrato, depois de conferir todos os campos e os dados."""
    if not _id_valido(id_execucao):
        return {"gravado": False, "problemas": ["id_execucao inválido"]}
    if numero_agente not in AGENTES:
        return {"gravado": False, "problemas": ["numero_agente deve ser de 1 a 6"]}
    problemas = _problemas_mensagem(mensagem, numero_agente)
    if mensagem.get("id_execucao") != id_execucao:
        problemas.append("id_execucao da mensagem diferente do informado")
    if problemas:
        return {"gravado": False, "problemas": problemas}
    if numero_agente == 2 and mensagem.get("status") == "sucesso":
        # Concorrentes reais encontrados vão para a base no GitHub (em segundo plano)
        _agendar_base(mensagem, id_execucao)
    if id_execucao == ID_EXEMPLO:
        # Teste em cima do exemplo: confere o formato, mas não substitui o oficial
        return {"gravado": False, "teste_aprovado": True,
                "aviso": "Saída válida. Com id EXEMPLO nada é gravado no servidor, para não "
                         "alterar o exemplo oficial; a cópia local fica em saidas/."}
    pasta = PASTA_ARMAZENAMENTO / id_execucao
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / _arquivo_saida(numero_agente)).write_text(
        json.dumps(mensagem, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"gravado": True, "arquivo": f"{id_execucao}/{_arquivo_saida(numero_agente)}"}


@mcp.tool
def ler_saida_agente(numero_agente: int, id_execucao: str = ID_EXEMPLO) -> dict:
    """[Todos] Retorna a saída gravada por um agente (1 Público, 2 Concorrência,
    3 Canais, 4 Criativo, 5 Simulador de Performance, 6 Financeiro) numa
    execução. Com id 'EXEMPLO', usa as saídas do exemplo oficial."""
    if numero_agente not in AGENTES:
        return {"erro": "numero_agente deve ser de 1 a 6"}
    if not _id_valido(id_execucao):
        return {"erro": "id_execucao inválido"}
    s = _saida(numero_agente, id_execucao)
    if s is None:
        return {"erro": f"O agente {numero_agente:02d} ainda não gravou saída em {id_execucao}"}
    return s


@mcp.tool
def listar_execucoes() -> list[dict]:
    """[Orquestrador] Lista as execuções guardadas no servidor e quais agentes
    já gravaram saída em cada uma (o EXEMPLO sempre aparece)."""
    return _listar_execucoes()


def _listar_execucoes() -> list[dict]:
    resultado = [{"id_execucao": ID_EXEMPLO, "tem_briefing": True,
                  "agentes_concluidos": [n for n in AGENTES
                                         if (PASTA_EXEMPLOS / _arquivo_saida(n)).exists()]}]
    if PASTA_ARMAZENAMENTO.exists():
        for pasta in sorted(PASTA_ARMAZENAMENTO.iterdir()):
            if pasta.is_dir() and pasta.name != ID_EXEMPLO:
                feitos = [n for n in AGENTES if (pasta / _arquivo_saida(n)).exists()]
                resultado.append({"id_execucao": pasta.name,
                                  "tem_briefing": (pasta / "briefing.json").exists(),
                                  "agentes_concluidos": feitos})
    return resultado


# ---------------------------------------------------------------- dados ---

@mcp.tool
def ler_concorrentes(segmento: str | None = None) -> dict:
    """[02 Concorrência] RESERVA: base fictícia de concorrentes, para quando
    buscar_concorrentes_web falhar. Com 'segmento' (ex.: o segmento do
    briefing), filtra pelos concorrentes daquele segmento. Todos são
    simulados, nenhum é real."""
    base = _ler_json(PASTA_DADOS / "concorrentes.json")
    if base is None:
        return {"erro": "Base de concorrentes ainda não foi publicada"}
    lista = base.get("concorrentes", [])
    segmentos = sorted({c.get("segmento", "") for c in lista})
    if segmento:
        filtrados = [c for c in lista if segmento.lower() in c.get("segmento", "").lower()
                     or c.get("segmento", "").lower() in segmento.lower()]
        if not filtrados:
            return {"erro": f"Nenhum concorrente no segmento '{segmento}'",
                    "segmentos_disponiveis": segmentos}
        lista = filtrados
    return {"tipo": "simulado", "segmentos_disponiveis": segmentos, "concorrentes": lista}


# --- Busca de concorrentes na internet (Tavily) ------------------------------
# Chave em TAVILY_API_KEY (variável de ambiente do Render; nunca no GitHub).
# Plano grátis do Tavily: 1.000 buscas por mês, 1 crédito por busca.

TAVILY_URL = "https://api.tavily.com/search"
MAX_CONSULTAS = 3
_BUSCAS_CACHE: dict[str, list[dict]] = {}
_URLS_BUSCADAS: dict[str, dict] = {}   # link -> título, trecho e consulta


def _normalizar_url(url: str) -> str:
    return url.strip().split("#")[0].rstrip("/").lower()


def _url_buscada(url: str) -> bool:
    return _normalizar_url(url) in _URLS_BUSCADAS


async def _tavily(consulta: str, max_resultados: int) -> list[dict]:
    import httpx
    chave = (os.environ.get("TAVILY_API_KEY") or "").strip()
    corpo = {"query": consulta, "search_depth": "basic", "max_results": max_resultados,
             "country": "brazil", "include_answer": False}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(TAVILY_URL, json=corpo, headers={"Authorization": f"Bearer {chave}"})
    if r.status_code != 200:
        raise RuntimeError(f"Tavily respondeu {r.status_code}: {r.text[:200]}")
    return r.json().get("results", [])


@mcp.tool
async def buscar_concorrentes_web(consultas: list[str], max_resultados_por_busca: int = 5) -> dict:
    """[02 Concorrência] Pesquisa concorrentes REAIS na internet (Tavily).
    Passe de 1 a 3 consultas curtas em português, montadas com o produto, o
    segmento e a cidade/região do briefing (ex.: "velas artesanais Campinas",
    "loja de aromas artesanais Instagram"). Devolve título, link e um trecho
    de cada página. Use só o que estiver nos trechos e cite o link em
    "fonte". Se der erro, use ler_concorrentes (base fictícia) como reserva."""
    if not (os.environ.get("TAVILY_API_KEY") or "").strip():
        return {"erro": "Busca na internet desligada (falta TAVILY_API_KEY no servidor). "
                        "Use ler_concorrentes (base fictícia) e marque \"tipo\": \"simulado\"."}
    consultas = [c.strip() for c in consultas if isinstance(c, str) and c.strip()][:MAX_CONSULTAS]
    if not consultas:
        return {"erro": "Passe de 1 a 3 consultas de busca"}
    n = max(1, min(int(max_resultados_por_busca or 5), 8))
    resultados, vistos, erros = [], set(), []
    for consulta in consultas:
        chave = f"{consulta.lower()}|{n}"
        try:
            if chave not in _BUSCAS_CACHE:
                _BUSCAS_CACHE[chave] = await _tavily(consulta, n)
        except Exception as e:  # rede, chave inválida, limite do plano
            erros.append(f"{consulta}: {e}")
            continue
        for item in _BUSCAS_CACHE[chave]:
            url = str(item.get("url") or "")
            if not url or _normalizar_url(url) in vistos:
                continue
            vistos.add(_normalizar_url(url))
            achado = {"consulta": consulta, "titulo": item.get("title", ""), "url": url,
                      "trecho": " ".join(str(item.get("content", "")).split())[:600]}
            _URLS_BUSCADAS[_normalizar_url(url)] = achado
            resultados.append(achado)
    if not resultados:
        return {"erro": "A busca não trouxe resultados. Use ler_concorrentes (base fictícia) "
                        "e marque \"tipo\": \"simulado\".", "detalhes": erros}
    return {
        "tipo": "real", "fonte": "Tavily (busca na internet)", "consultas": consultas,
        "resultados": resultados, "erros": erros,
        "aviso": ("Resultados reais da internet. Cada concorrente analisado deve ter \"tipo\": "
                  "\"real\" e \"fonte\" com o link de onde a informação veio. Não invente preço, "
                  "seguidores ou canais que não estejam nos trechos."),
    }


# --- Base de concorrentes reais no GitHub ------------------------------------
# Todo concorrente "real" que o Agente 02 entrega é guardado no arquivo
# concorrentes_encontrados.json, num ramo separado do repositório
# (base-concorrentes). Ramo separado porque o Render só republica quando o
# ramo main muda; salvar no main reiniciaria o servidor no meio da rodada.
# Chave: GITHUB_TOKEN (token com permissão "Contents: read and write" só neste
# repositório), nas variáveis do Render. Nunca no código.

GITHUB_REPO = os.environ.get("GITHUB_REPO", "Schaustz/mcp-server")
GITHUB_RAMO = os.environ.get("GITHUB_RAMO_BASE", "base-concorrentes")
ARQUIVO_BASE = "concorrentes_encontrados.json"
_GH_API = "https://api.github.com"
_BASE_CACHE: dict = {"dados": None, "lido_em": 0.0}
_BASE_STATUS: dict = {"status": "nada salvo desde que o servidor ligou", "quando": "", "detalhe": ""}
_BASE_TRAVA: asyncio.Lock | None = None
_TAREFAS_BASE: set = set()


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "mcp-campaign-commander",
         "X-GitHub-Api-Version": "2022-11-28"}
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _sem_acento(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


async def _gh_ler_base(http) -> tuple[dict, str | None]:
    """Lê o arquivo da base no ramo. Devolve (dados, sha); sem arquivo: base vazia."""
    import base64
    r = await http.get(f"{_GH_API}/repos/{GITHUB_REPO}/contents/{ARQUIVO_BASE}",
                       params={"ref": GITHUB_RAMO}, headers=_gh_headers())
    if r.status_code == 404:
        return {"concorrentes": []}, None
    if r.status_code != 200:
        raise RuntimeError(f"GitHub respondeu {r.status_code} ao ler a base: {r.text[:200]}")
    j = r.json()
    dados = json.loads(base64.b64decode(j["content"]).decode("utf-8"))
    return dados, j["sha"]


async def _gh_garantir_ramo(http) -> None:
    r = await http.get(f"{_GH_API}/repos/{GITHUB_REPO}/git/ref/heads/{GITHUB_RAMO}", headers=_gh_headers())
    if r.status_code == 200:
        return
    main = await http.get(f"{_GH_API}/repos/{GITHUB_REPO}/git/ref/heads/main", headers=_gh_headers())
    if main.status_code != 200:
        raise RuntimeError(f"GitHub respondeu {main.status_code} ao ler o ramo main: {main.text[:200]}")
    c = await http.post(f"{_GH_API}/repos/{GITHUB_REPO}/git/refs", headers=_gh_headers(),
                        json={"ref": f"refs/heads/{GITHUB_RAMO}", "sha": main.json()["object"]["sha"]})
    if c.status_code not in (201, 422):  # 422: alguém criou ao mesmo tempo
        raise RuntimeError(f"GitHub respondeu {c.status_code} ao criar o ramo: {c.text[:200]}")


async def _gh_salvar_base(http, dados: dict, sha: str | None, mensagem: str) -> int:
    import base64
    corpo = {"message": mensagem, "branch": GITHUB_RAMO,
             "content": base64.b64encode(json.dumps(dados, ensure_ascii=False, indent=2)
                                         .encode("utf-8")).decode()}
    if sha:
        corpo["sha"] = sha
    r = await http.put(f"{_GH_API}/repos/{GITHUB_REPO}/contents/{ARQUIVO_BASE}",
                       headers=_gh_headers(), json=corpo)
    if r.status_code not in (200, 201, 409, 422):
        raise RuntimeError(f"GitHub respondeu {r.status_code} ao salvar: {r.text[:200]}")
    return r.status_code


def _mesclar_na_base(base: dict, mensagem: dict, briefing: dict, id_execucao: str) -> int:
    """Junta os concorrentes reais da saída do 02 na base. Devolve quantos entraram ou mudaram."""
    agora = datetime.now().isoformat(timespec="seconds")
    lista = base.setdefault("concorrentes", [])
    por_nome = {_sem_acento(c.get("nome", "")): c for c in lista}
    mudou = 0
    for c in _lista_dicts(mensagem.get("dados", {}).get("concorrentes_analisados")):
        fonte = str(c.get("fonte") or "")
        if c.get("tipo") != "real" or not fonte.startswith("http") or not c.get("nome"):
            continue
        chave = _sem_acento(c["nome"])
        item = por_nome.get(chave)
        if item is None:
            item = {"nome": c["nome"], "tipo": "real", "fontes": [], "segmentos": [], "regioes": [],
                    "posicionamento": "", "trecho_da_fonte": "", "avaliacoes": [],
                    "vezes_encontrado": 0, "primeira_vez": agora, "ultima_vez": agora}
            lista.append(item)
            por_nome[chave] = item
        if fonte not in item["fontes"]:
            item["fontes"].append(fonte)
        for campo, valor in (("segmentos", briefing.get("segmento")), ("regioes", briefing.get("regiao"))):
            if valor and valor not in item[campo]:
                item[campo].append(valor)
        if c.get("posicionamento"):
            item["posicionamento"] = c["posicionamento"]
        achado = _URLS_BUSCADAS.get(_normalizar_url(fonte))
        if achado and achado.get("trecho"):
            item["trecho_da_fonte"] = achado["trecho"]
        item["avaliacoes"] = (item["avaliacoes"] + [{
            "data": agora, "id_execucao": id_execucao, "empresa_analisada": briefing.get("empresa"),
            "ameaca": c.get("ameaca"), "justificativa": c.get("justificativa")}])[-10:]
        item["vezes_encontrado"] += 1
        item["ultima_vez"] = agora
        mudou += 1
    base["tipo"] = "real"
    base["observacao"] = ("Concorrentes reais encontrados na internet pelo Agente 02 (Tavily). "
                          "Informações de trechos públicos; podem estar desatualizadas.")
    base["atualizado_em"] = agora
    return mudou


def _lista_dicts(itens) -> list[dict]:
    return [x for x in (itens if isinstance(itens, list) else []) if isinstance(x, dict)]


async def _registrar_na_base(mensagem: dict, id_execucao: str) -> None:
    import httpx
    global _BASE_TRAVA
    reais = [c for c in _lista_dicts(mensagem.get("dados", {}).get("concorrentes_analisados"))
             if c.get("tipo") == "real"]
    if not reais:
        return
    if not (os.environ.get("GITHUB_TOKEN") or "").strip():
        _BASE_STATUS.update(status="não salvo", quando=datetime.now().isoformat(timespec="seconds"),
                            detalhe="falta GITHUB_TOKEN no servidor")
        return
    _BASE_TRAVA = _BASE_TRAVA or asyncio.Lock()
    briefing = _briefing(id_execucao) or {}
    try:
        async with _BASE_TRAVA, httpx.AsyncClient(timeout=30) as http:
            await _gh_garantir_ramo(http)
            for _ in range(3):  # se outro salvamento passar na frente, lê de novo
                base, sha = await _gh_ler_base(http)
                n = _mesclar_na_base(base, mensagem, briefing, id_execucao)
                codigo = await _gh_salvar_base(
                    http, base, sha, f"Base de concorrentes: +{n} de {briefing.get('empresa', id_execucao)}")
                if codigo in (200, 201):
                    _BASE_CACHE.update(dados=base, lido_em=time.time())
                    _BASE_STATUS.update(status="salvo", quando=base["atualizado_em"],
                                        detalhe=f"{n} concorrente(s) de {id_execucao}")
                    return
            raise RuntimeError("conflito ao salvar no GitHub depois de 3 tentativas")
    except Exception as e:
        _BASE_STATUS.update(status="erro ao salvar", quando=datetime.now().isoformat(timespec="seconds"),
                            detalhe=str(e)[:300])
        print(f"[base de concorrentes] {e}", file=sys.stderr)


def _agendar_base(mensagem: dict, id_execucao: str) -> None:
    tarefa = asyncio.get_running_loop().create_task(_registrar_na_base(mensagem, id_execucao))
    _TAREFAS_BASE.add(tarefa)
    tarefa.add_done_callback(_TAREFAS_BASE.discard)


async def _base_atual(max_idade_s: float = 60) -> dict:
    import httpx
    if _BASE_CACHE["dados"] is not None and time.time() - _BASE_CACHE["lido_em"] < max_idade_s:
        return _BASE_CACHE["dados"]
    async with httpx.AsyncClient(timeout=30) as http:
        base, _ = await _gh_ler_base(http)
    _BASE_CACHE.update(dados=base, lido_em=time.time())
    return base


@mcp.tool
async def ler_historico_concorrentes(segmento: str | None = None, regiao: str | None = None,
                                     limite: int = 15) -> dict:
    """[02 Concorrência] Concorrentes REAIS já encontrados em execuções
    anteriores (base guardada no GitHub). Filtre pelo segmento e/ou pela
    cidade/região do briefing. Serve para comparar com a busca de agora: quem
    aparece há mais tempo, quantas vezes foi encontrado e a ameaça que recebeu.
    Pode citar um concorrente do histórico com "tipo": "real" e "fonte" igual
    a um dos links em "fontes"."""
    try:
        base = await _base_atual()
    except Exception as e:
        return {"erro": f"Não foi possível ler a base de concorrentes: {e}"}
    lista = _lista_dicts(base.get("concorrentes"))
    seg, reg = _sem_acento(segmento or ""), _sem_acento(regiao or "")

    def combina(valores: list, filtro: str) -> bool:
        if not filtro:
            return True
        vs = [_sem_acento(v) for v in valores]
        palavras = [p for p in re.split(r"[\s,/-]+", filtro) if len(p) > 3]
        return any(filtro in v or v in filtro or any(p in v for p in palavras) for v in vs)

    filtrados = [c for c in lista if combina(c.get("segmentos", []), seg) and combina(c.get("regioes", []), reg)]
    filtrados.sort(key=lambda c: (c.get("vezes_encontrado", 0), c.get("ultima_vez", "")), reverse=True)
    filtrados = filtrados[:max(1, min(int(limite or 15), 40))]
    for c in filtrados:  # links do histórico também valem como fonte
        for f in c.get("fontes", []):
            _URLS_BUSCADAS.setdefault(_normalizar_url(f), {"url": f, "titulo": c.get("nome"),
                                                           "trecho": c.get("trecho_da_fonte", ""),
                                                           "consulta": "histórico"})
    return {
        "tipo": "real", "total_na_base": len(lista), "encontrados": len(filtrados),
        "atualizado_em": base.get("atualizado_em"),
        "concorrentes": [{
            "nome": c.get("nome"), "fontes": c.get("fontes", []), "segmentos": c.get("segmentos", []),
            "regioes": c.get("regioes", []), "posicionamento": c.get("posicionamento", ""),
            "trecho_da_fonte": c.get("trecho_da_fonte", ""),
            "vezes_encontrado": c.get("vezes_encontrado", 0), "primeira_vez": c.get("primeira_vez"),
            "ultima_vez": c.get("ultima_vez"),
            "ultima_avaliacao": (c.get("avaliacoes") or [{}])[-1],
        } for c in filtrados],
        "aviso": "Informações de buscas anteriores; confira se ainda valem antes de usar.",
    }


@mcp.tool
def ler_premissas_simulacao() -> dict:
    """[03 Canais, 05 Simulador, 06 Financeiro] Retorna a tabela fictícia de
    premissas por canal (CPM, CTR, conversão, engajamento, frequência,
    seguidores), os multiplicadores dos 3 cenários e as regras de
    distribuição do orçamento."""
    p = _premissas()
    return p if p else {"erro": "Tabela de premissas ainda não foi publicada"}


@mcp.tool
def ler_dados(nome: str) -> dict:
    """[Todos] Atalho para as bases fictícias: 'concorrentes' ou
    'premissas_simulacao'."""
    if nome == "concorrentes":
        return ler_concorrentes()
    if nome == "premissas_simulacao":
        return ler_premissas_simulacao()
    return {"erro": "nome deve ser 'concorrentes' ou 'premissas_simulacao'"}


# ------------------------------------------------------------- validação ---

@mcp.tool
def validar_briefing(briefing: dict) -> dict:
    """[Orquestrador] Confere campos obrigatórios, objetivo, orçamento e
    ticket médio. Retorna {'valido': bool, 'problemas': [...]}."""
    problemas = _problemas_briefing(briefing)
    return {"valido": not problemas, "problemas": problemas}


@mcp.tool
def validar_canais(canais: list[str]) -> dict:
    """[03 Canais] Confere se os canais estão na lista fechada e se a
    quantidade respeita as regras (mínimo e máximo de canais)."""
    invalidos = [c for c in canais if c not in CANAIS_SUPORTADOS]
    regras = _premissas().get("regras_distribuicao", {})
    mn, mx = regras.get("minimo_canais", 2), regras.get("maximo_canais", 5)
    problemas = []
    if invalidos:
        problemas.append(f"Canais fora da lista: {invalidos}")
    if not mn <= len(set(canais)) <= mx:
        problemas.append(f"Escolha de {mn} a {mx} canais (veio {len(set(canais))})")
    return {"valido": not problemas, "canais_invalidos": invalidos, "problemas": problemas}


@mcp.tool
def verificar_mensagens_criativo(canais_escolhidos: list[str], mensagens: list[dict]) -> dict:
    """[04 Criativo] Confere se existe uma mensagem para cada canal escolhido
    e se os textos respeitam os limites de referência de cada canal (ex.:
    título do Google Pesquisa até 30 caracteres). 'mensagens' segue o formato
    de mensagens_por_canal: [{"canal", "titulo", "texto", ...}]."""
    problemas = []
    canais_msg = [m.get("canal") for m in mensagens]
    faltando = [c for c in canais_escolhidos if c not in canais_msg]
    if faltando:
        problemas.append(f"Sem mensagem para: {faltando}")
    sobrando = [c for c in canais_msg if c not in canais_escolhidos]
    if sobrando:
        problemas.append(f"Mensagem para canal não escolhido: {sobrando}")
    for m in mensagens:
        limites = LIMITES_TEXTO.get(m.get("canal"), {})
        for campo, limite in limites.items():
            tamanho = len(m.get(campo) or "")
            if tamanho > limite:
                problemas.append(f"{m.get('canal')}: {campo} com {tamanho} caracteres "
                                 f"(limite de referência {limite})")
    return {"valido": not problemas, "problemas": problemas,
            "limites_de_referencia": LIMITES_TEXTO}


@mcp.tool
def verificar_saida(numero_agente: int, mensagem: dict) -> dict:
    """[Todos] Confere se uma mensagem segue o formato padrão do contrato e o
    formato_dados do agente, sem gravar. Útil para testar antes de entregar."""
    if numero_agente not in AGENTES:
        return {"valido": False, "problemas": ["numero_agente deve ser de 1 a 6"]}
    problemas = _problemas_mensagem(mensagem, numero_agente)
    return {"valido": not problemas, "problemas": problemas}


@mcp.tool
def validar_distribuicao(orcamento_total: float, percentuais_por_canal: dict[str, float]) -> dict:
    """[06 Financeiro] Confere a distribuição em percentuais contra as regras:
    canais da lista, soma 100, número de canais e mínimo/máximo por canal."""
    regras = _premissas().get("regras_distribuicao", {})
    problemas = []
    invalidos = [c for c in percentuais_por_canal if c not in CANAIS_SUPORTADOS]
    if invalidos:
        problemas.append(f"Canais fora da lista: {invalidos}")
    soma = round(sum(percentuais_por_canal.values()), 4)
    if soma != 100:
        problemas.append(f"Os percentuais somam {soma}, devem somar 100")
    mn, mx = regras.get("minimo_canais", 2), regras.get("maximo_canais", 5)
    if not mn <= len(percentuais_por_canal) <= mx:
        problemas.append(f"Use de {mn} a {mx} canais")
    pmin = regras.get("percentual_minimo_por_canal", 0)
    pmax = regras.get("percentual_maximo_por_canal", 100)
    for canal, pct in percentuais_por_canal.items():
        if not pmin <= pct <= pmax:
            problemas.append(f"{canal}: {pct}% fora do intervalo {pmin}% a {pmax}%")
    if orcamento_total <= 0:
        problemas.append("orcamento_total deve ser maior que zero")
    return {"valido": not problemas, "problemas": problemas, "regras": regras}


# ---------------------------------------------------------------- cálculo ---

@mcp.tool
def simular_canais(canais: list[str], investimento_por_canal: float = 1000,
                   id_execucao: str = ID_EXEMPLO) -> dict:
    """[05 Simulador] Simula cada canal com o mesmo investimento (padrão
    R$ 1.000) nos cenários pessimista, realista e otimista, usando a tabela de
    premissas. Retorna impressões, alcance, cliques, engajamentos, novos
    seguidores, conversões, CPC, custo por seguidor e receita (se o briefing
    tiver ticket médio). Passe SEMPRE o id_execucao da execução atual: o
    ticket médio vem do briefing dela. Simulação — não representa resultado real."""
    invalidos = [c for c in canais if c not in CANAIS_SUPORTADOS]
    if invalidos:
        return {"erro": f"Canais fora da lista: {invalidos}"}
    if investimento_por_canal <= 0:
        return {"erro": "investimento_por_canal deve ser maior que zero"}
    if not _premissas():
        return {"erro": "Tabela de premissas ainda não foi publicada"}
    b = _briefing(id_execucao) or {}
    ticket = b.get("ticket_medio") or None
    return {
        "tipo": "simulado",
        "base_simulacao": f"R$ {investimento_por_canal:,.2f} por canal".replace(",", "X")
                          .replace(".", ",").replace("X", "."),
        "ticket_medio_usado": ticket,
        "resultados_por_canal": {c: _simular(c, investimento_por_canal, ticket) for c in canais},
        "aviso": "Simulação — não representa resultado real",
    }


@mcp.tool
def calcular_distribuicao_orcamento(orcamento_total: float,
                                    percentuais_por_canal: dict[str, float]) -> dict:
    """[06 Financeiro] Converte percentuais por canal em reais. Os percentuais
    devem somar 100 e a soma dos valores fecha exatamente com o orçamento
    (centavos de arredondamento vão para o maior canal).
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
        "distribuicao": [{"canal": c, "percentual": percentuais_por_canal[c], "valor": v / 100}
                         for c, v in valores.items()],
        "total_distribuido": sum(valores.values()) / 100,
        "soma_confere": sum(valores.values()) == total_centavos,
    }


@mcp.tool
def projetar_resultados(valores_por_canal: dict[str, float],
                        id_execucao: str = ID_EXEMPLO) -> dict:
    """[06 Financeiro] Projeta a campanha inteira com os valores em reais de
    cada canal (saída de calcular_distribuicao_orcamento), nos 3 cenários:
    totais de impressões, alcance, cliques, engajamentos, novos seguidores,
    conversões, receita, ROAS e ROI (ROI só se o briefing tiver margem).
    Passe SEMPRE o id_execucao da execução atual: ticket médio e margem vêm do
    briefing dela. Simulação — não representa resultado real."""
    invalidos = [c for c in valores_por_canal if c not in CANAIS_SUPORTADOS]
    if invalidos:
        return {"erro": f"Canais fora da lista: {invalidos}"}
    if not _premissas():
        return {"erro": "Tabela de premissas ainda não foi publicada"}
    b = _briefing(id_execucao)
    if b is None:
        return {"erro": f"Nenhum briefing para {id_execucao}"}
    return _projetar(valores_por_canal, b)


def _projetar(valores_por_canal: dict[str, float], b: dict) -> dict:
    ticket = b.get("ticket_medio") or None
    margem = b.get("margem_contribuicao_percentual")
    investimento = round(sum(valores_por_canal.values()), 2)

    por_canal = {c: _simular(c, v, ticket) for c, v in valores_por_canal.items()}
    projecao = {}
    for cenario in CENARIOS:
        tot = {"investimento": investimento}
        for k in ["impressoes", "alcance", "cliques", "engajamentos", "novos_seguidores"]:
            tot[k] = sum(por_canal[c][cenario][k] for c in por_canal)
        conv = sum(por_canal[c][cenario]["conversoes"] for c in por_canal)
        tot["conversoes"] = round(conv)
        tot["custo_por_seguidor"] = (round(investimento / tot["novos_seguidores"], 2)
                                     if tot["novos_seguidores"] else None)
        if ticket:
            receita = round(sum(por_canal[c][cenario]["receita"] for c in por_canal), 2)
            tot["receita"] = receita
            tot["roas"] = round(receita / investimento, 2) if investimento else None
            if margem is not None and investimento:
                tot["roi_percentual"] = round(
                    (receita * margem / 100 - investimento) / investimento * 100, 2)
            else:
                tot["roi_percentual"] = None
        projecao[cenario] = tot
    return {
        "tipo": "simulado",
        "orcamento_total_briefing": b.get("orcamento_total"),
        "investimento_projetado": investimento,
        "fecha_com_orcamento": abs(investimento - float(b.get("orcamento_total", 0))) < 0.01,
        "totais_por_cenario": projecao,
        "por_canal": por_canal,
        "observacao": ("ROAS = receita / investimento. ROI = (receita x margem - investimento) "
                       "/ investimento. Receita não é lucro."),
        "aviso": "Simulação — não representa resultado real",
    }


@mcp.tool
def calcular_indicadores(investimento: float, receita: float,
                         margem_contribuicao_percentual: float | None = None) -> dict:
    """[06 Financeiro] Calcula ROAS e, se houver margem, ROI. Receita não é
    lucro e ROAS não é ROI. ROAS = receita / investimento.
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


# ------------------------------------------------------------ orquestrador ---

@mcp.tool
def validar_execucao(id_execucao: str = ID_EXEMPLO) -> dict:
    """[Orquestrador] Faz as validações cruzadas do contrato numa execução:
    todos os agentes com status sucesso; canais do 03 na lista; Criativo com
    mensagem para cada canal escolhido; Financeiro só com canais escolhidos e
    soma igual ao orcamento_total."""
    return _validar_execucao(id_execucao)


def _validar_execucao(id_execucao: str) -> dict:
    if not _id_valido(id_execucao):
        return {"erro": "id_execucao inválido"}
    b = _briefing(id_execucao)
    if b is None:
        return {"erro": f"Nenhum briefing para {id_execucao}"}
    status, problemas = {}, []
    saidas = {n: _saida(n, id_execucao) for n in AGENTES}
    for n, s in saidas.items():
        status[AGENTES[n]["chave"]] = s.get("status") if s else "pendente"
        if s and s.get("status") != "sucesso":
            problemas.append(f"Agente {n:02d} com status {s.get('status')}")
    if saidas[3] and saidas[3].get("status") == "sucesso":
        escolhidos = _canais_da_lista(saidas[3]["dados"].get("canais_escolhidos"))
        invalidos = [c for c in escolhidos if c not in CANAIS_SUPORTADOS]
        if invalidos:
            problemas.append(f"Canais do 03 fora da lista: {invalidos}")
        if saidas[4] and saidas[4].get("status") == "sucesso":
            msgs = _canais_da_lista(saidas[4]["dados"].get("mensagens_por_canal"))
            faltando = [c for c in escolhidos if c not in msgs]
            if faltando:
                problemas.append(f"Criativo sem mensagem para: {faltando}")
        if saidas[6] and saidas[6].get("status") == "sucesso":
            dist = saidas[6]["dados"].get("distribuicao", [])
            canais_fin = _canais_da_lista(dist)
            fora = [c for c in canais_fin if c not in escolhidos]
            if fora:
                problemas.append(f"Financeiro com canal não escolhido pelo 03: {fora}")
    if saidas[6] and saidas[6].get("status") == "sucesso":
        total = round(sum(float(d.get("valor", 0)) for d in saidas[6]["dados"].get("distribuicao", [])), 2)
        if abs(total - float(b.get("orcamento_total", 0))) > 0.01:
            problemas.append(f"Soma do Financeiro ({total}) diferente do orçamento "
                             f"({b.get('orcamento_total')})")
    pendentes = [k for k, v in status.items() if v == "pendente"]
    return {"id_execucao": id_execucao, "status_agentes": status, "pendentes": pendentes,
            "valido": not problemas and not pendentes, "problemas": problemas}


# ------------------------------------------------------------ página raiz ---

@mcp.custom_route("/", methods=["GET"])
async def pagina_inicial(request: Request) -> JSONResponse:
    """Abrir o link no navegador mostra que o servidor está no ar
    (e acorda o servidor no plano grátis do Render)."""
    return JSONResponse({
        "servidor": "Marketing Campaign Commander — MCP",
        "status": "no ar",
        "endpoint_mcp": "/mcp",
        "exemplo": "id_execucao EXEMPLO",
        "painel": "/painel",
    })


# ------------------------------------------------------------------ painel ---
# Páginas só de leitura para acompanhar as execuções pelo navegador.

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--txt:#1d2330;--sub:#5d6575;--borda:#e1e4ea;
--ok:#1f8a4c;--okbg:#e5f5ec;--erro:#b42318;--errobg:#fde8e7;--pend:#8a6a00;--pendbg:#fdf4d8;
--link:#2b59c3;--code:#f1f3f6}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--txt:#e7e9ee;--sub:#a0a7b4;
--borda:#2e333c;--ok:#5fd394;--okbg:#173626;--erro:#ff8a80;--errobg:#3d1c1a;--pend:#f2c94c;
--pendbg:#3a3112;--link:#8fb0ff;--code:#151920}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}
.sub{color:var(--sub);margin:0 0 20px}a{color:var(--link);text-decoration:none}
a:hover{text-decoration:underline}
.card{background:var(--card);border:1px solid var(--borda);border-radius:10px;padding:14px 16px;margin:10px 0;overflow-x:auto}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px 6px;
border-bottom:1px solid var(--borda);vertical-align:top}th{color:var(--sub);font-weight:600;font-size:13px}
.tag{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600}
.sucesso{color:var(--ok);background:var(--okbg)}.erro{color:var(--erro);background:var(--errobg)}
.pendente{color:var(--pend);background:var(--pendbg)}
details{background:var(--card);border:1px solid var(--borda);border-radius:10px;margin:10px 0}
summary{cursor:pointer;padding:12px 16px;font-weight:600}
pre{margin:0;padding:12px 16px;background:var(--code);border-top:1px solid var(--borda);
overflow-x:auto;font-size:12.5px;line-height:1.45;white-space:pre-wrap;word-break:break-word}
.chips span{margin-right:4px}.botao{display:inline-block;background:#2b59c3;color:#fff;padding:8px 16px;border-radius:8px;font-weight:600}.botao:hover{text-decoration:none;opacity:.9}label{display:block;font-weight:600;margin:12px 0 4px}input,select,textarea{width:100%;padding:8px 10px;border:1px solid var(--borda);border-radius:8px;background:var(--card);color:var(--txt);font:inherit}textarea{min-height:70px}.duas{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:600px){.duas{grid-template-columns:1fr}}.erro-box{color:var(--erro);background:var(--errobg);border-radius:8px;padding:10px 14px}.dica{color:var(--sub);font-size:13px;margin:4px 0 0;line-height:1.45}.dica b{color:var(--txt)}.log{font:12.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap}.aviso{color:var(--sub);font-size:13px;margin-top:24px}
"""


def _pagina(titulo: str, corpo: str, atualizar: bool = False) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="10">' if atualizar else ""
    return HTMLResponse(
        f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">{meta}'
        f"<title>{escape(titulo)}</title><style>{_CSS}</style></head>"
        f"<body><main>{corpo}<p class='aviso'>Simulação — não representa resultado real. "
        f"Execuções reais somem quando o servidor fica 15 minutos sem uso.</p></main></body></html>")


def _reais(valor) -> str:
    try:
        return f"{float(valor):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(valor)


def _tag(status: str) -> str:
    status = status if status in ("sucesso", "erro") else "pendente"
    return f'<span class="tag {status}">{status}</span>'


@mcp.custom_route("/concorrentes", methods=["GET"])
async def pagina_concorrentes(request: Request) -> HTMLResponse:
    """Base de concorrentes reais guardada no GitHub."""
    try:
        base = await _base_atual(max_idade_s=20)
        erro = ""
    except Exception as e:
        base, erro = {"concorrentes": []}, str(e)
    lista = sorted(_lista_dicts(base.get("concorrentes")),
                   key=lambda c: c.get("ultima_vez", ""), reverse=True)
    linhas = []
    for c in lista:
        av = (c.get("avaliacoes") or [{}])[-1]
        links = " ".join(f'<a href="{escape(f)}" target="_blank" rel="noopener">fonte {i + 1}</a>'
                         for i, f in enumerate(c.get("fontes", [])))
        linhas.append(
            f"<tr><td><b>{escape(str(c.get('nome', '')))}</b><br><span class='sub'>{links}</span></td>"
            f"<td>{escape(', '.join(c.get('segmentos', [])))}<br>"
            f"<span class='sub'>{escape(', '.join(c.get('regioes', [])))}</span></td>"
            f"<td>{escape(str(c.get('posicionamento', '')))}</td>"
            f"<td>{escape(str(av.get('ameaca', '—')))}<br><span class='sub'>"
            f"{escape(str(av.get('empresa_analisada') or ''))}</span></td>"
            f"<td>{c.get('vezes_encontrado', 0)}</td>"
            f"<td>{escape(str(c.get('ultima_vez', ''))[:10])}</td></tr>")
    tabela = ("<div class='card'><table><tr><th>Concorrente</th><th>Segmento / região</th>"
              "<th>Posicionamento</th><th>Última ameaça</th><th>Vezes</th><th>Última vez</th></tr>"
              + "".join(linhas) + "</table></div>") if linhas else (
              "<div class='card'>Nenhum concorrente guardado ainda. Eles entram aqui quando o "
              "Agente 02 encontra concorrentes reais na internet.</div>")
    st = _BASE_STATUS
    corpo = ("<p><a href='/painel'>← Painel</a></p><h1>Base de concorrentes reais</h1>"
             f"<p class='sub'>{len(lista)} concorrente(s) encontrados na internet pelo Agente 02, "
             f"guardados no GitHub (ramo <code>{escape(GITHUB_RAMO)}</code>, arquivo "
             f"<code>{ARQUIVO_BASE}</code>). Informações de trechos públicos; podem estar desatualizadas.</p>"
             + (f"<p class='erro-box'>Não consegui ler a base: {escape(erro)}</p>" if erro else "")
             + tabela
             + f"<p class='sub'>Último salvamento: {escape(st['status'])} {escape(st['quando'])} "
               f"{escape(st['detalhe'])}</p>")
    return _pagina("Base de concorrentes", corpo)


@mcp.custom_route("/painel", methods=["GET"])
async def painel(request: Request) -> HTMLResponse:
    linhas = []
    for e in reversed(_listar_execucoes()):
        id_exec = e["id_execucao"]
        chips = []
        for n in AGENTES:
            s = _saida(n, id_exec)
            chips.append(f'<span title="{escape(AGENTES[n]["nome"])}">'
                         f'{_tag(s.get("status") if s else "pendente").replace(">", f">{n:02d} ", 1)}</span>')
        b = _briefing(id_exec) or {}
        linhas.append(f'<tr><td><a href="/painel/{escape(id_exec)}">{escape(id_exec)}</a></td>'
                      f'<td>{escape(str(b.get("empresa", "—")))}</td>'
                      f'<td class="chips">{"".join(chips)}</td></tr>')
    corpo = ("<h1>Marketing Campaign Commander</h1>"
             "<p class='sub'>Execuções guardadas no servidor MCP. A página atualiza sozinha a cada 10 s.</p>"
             "<p><a class='botao' href='/painel/novo'>+ Nova rodada no servidor</a> "
             "&nbsp;<a href='/concorrentes'>Base de concorrentes reais →</a></p>"
             "<div class='card'><table><tr><th>Execução</th><th>Empresa</th><th>Agentes</th></tr>"
             + "".join(linhas) + "</table></div>")
    return _pagina("Painel MCP", corpo, atualizar=True)


@mcp.custom_route("/painel/{id_execucao}", methods=["GET"])
async def painel_execucao(request: Request) -> HTMLResponse:
    id_exec = request.path_params["id_execucao"]
    if id_exec == "novo":
        return await nova_rodada_form(request)
    b = _briefing(id_exec) if _id_valido(id_exec) else None
    if b is None:
        corpo = (f"<p><a href='/painel'>← Execuções</a></p><h1>{escape(id_exec)}</h1>"
                 "<div class='card'>Execução não encontrada. Se ficou 15 minutos sem uso, o servidor "
                 "apagou; abra outra com TESTES/abrir_execucao.py.</div>")
        return _pagina(id_exec, corpo)

    linhas, detalhes = [], []
    for n, ficha in AGENTES.items():
        s = _saida(n, id_exec)
        status = s.get("status") if s else "pendente"
        quando = escape(str(s.get("data_hora", "")).replace("T", " ")) if s else ""
        linhas.append(f"<tr><td>{n:02d}</td><td>{escape(ficha['nome'])}</td>"
                      f"<td>Grupo {escape(ficha['grupo'])}</td><td>{_tag(status)}</td><td>{quando}</td></tr>")
        if s:
            detalhes.append(f"<details><summary>{n:02d} · {escape(ficha['nome'])} {_tag(status)}</summary>"
                            f"<pre>{escape(json.dumps(s, ensure_ascii=False, indent=2))}</pre></details>")

    v = _validar_execucao(id_exec)
    if v.get("valido"):
        validacao = _tag("sucesso").replace("sucesso<", "tudo certo<")
    elif v.get("problemas"):
        validacao = "<br>".join(escape(p) for p in v["problemas"])
    else:
        validacao = f"incompleta — faltam: {escape(', '.join(v.get('pendentes', [])))}"

    resumo = (f"<b>{escape(str(b.get('empresa', '')))}</b> · objetivo {escape(str(b.get('objetivo_campanha', '')))}"
              f" · orçamento R$ {escape(_reais(b.get('orcamento_total')))} · {escape(str(b.get('duracao_dias', '')))} dias")
    corpo = (f"<p><a href='/painel'>← Execuções</a></p><h1>{escape(id_exec)}</h1>"
             f"<p class='sub'>{resumo}. <a href='/painel/{escape(id_exec)}'>Atualizar</a></p>"
             "<div class='card'><table><tr><th>Nº</th><th>Agente</th><th>Grupo</th><th>Status</th>"
             "<th>Gravado em</th></tr>" + "".join(linhas) + "</table></div>"
             + _bloco_rodada(id_exec)
             + f"<div class='card'><b>Validação cruzada:</b> {validacao}</div>"
             + (f"<div class='card'><b>Relatório final:</b> <a href='/relatorio/{escape(id_exec)}'>abrir o "
                "relatório</a></div>" if (PASTA_ARMAZENAMENTO / id_exec / "relatorio_final.html").exists()
                else "<div class='card'><b>Relatório final:</b> ainda não publicado pelo Orquestrador.</div>")
             + "<h2>Saídas gravadas</h2>" + ("".join(detalhes) or "<div class='card'>Nenhuma ainda.</div>")
             + f"<details><summary>Briefing</summary><pre>{escape(json.dumps(b, ensure_ascii=False, indent=2))}"
             "</pre></details>")
    est = _estado(id_exec)
    return _pagina(id_exec, corpo, atualizar=bool(est and est.get("estado") == "rodando"))


def _bloco_rodada(id_exec: str) -> str:
    est = _estado(id_exec)
    if not est:
        return ""
    rotulo = {"rodando": "rodando no servidor (a página atualiza sozinha)", "concluida": "concluída",
              "parcial": "parcial (o fluxo parou antes do fim)", "erro": "erro"}.get(est.get("estado"), "")
    log = "\n".join(est.get("log", [])[-60:])
    return (f"<div class='card'><b>Rodada no servidor:</b> {escape(rotulo)}"
            f"<details open><summary>Registro</summary><pre class='log'>{escape(log)}</pre></details></div>")


# --------------------------------------------------------- relatório final ---
# O Orquestrador publica o relatório (POST) e cada pessoa baixa (GET).
# Não é uma ferramenta MCP, para o Gemini dos agentes não enxergar.

TAMANHO_MAX_RELATORIO = 3 * 1024 * 1024


@mcp.custom_route("/relatorio/{id_execucao}", methods=["GET"])
async def ver_relatorio(request: Request) -> HTMLResponse:
    id_exec = request.path_params["id_execucao"]
    arq = PASTA_ARMAZENAMENTO / id_exec / "relatorio_final.html" if _id_valido(id_exec) else None
    if arq is None or not arq.exists():
        corpo = (f"<p><a href='/painel'>← Execuções</a></p><h1>{escape(id_exec)}</h1>"
                 "<div class='card'>O relatório desta execução ainda não foi publicado. Ele aparece "
                 "aqui quando o Orquestrador terminar.</div>")
        resp = _pagina(id_exec, corpo)
        resp.status_code = 404
        return resp
    return HTMLResponse(arq.read_text(encoding="utf-8"))


@mcp.custom_route("/relatorio/{id_execucao}", methods=["POST"])
async def publicar_relatorio(request: Request) -> JSONResponse:
    id_exec = request.path_params["id_execucao"]
    if not _id_valido(id_exec) or id_exec == ID_EXEMPLO or _briefing(id_exec) is None:
        return JSONResponse({"publicado": False, "erro": "execução não encontrada"}, status_code=404)
    corpo = await request.body()
    if not corpo or len(corpo) > TAMANHO_MAX_RELATORIO:
        return JSONResponse({"publicado": False, "erro": "relatório vazio ou grande demais"},
                            status_code=400)
    (PASTA_ARMAZENAMENTO / id_exec / "relatorio_final.html").write_bytes(corpo)
    return JSONResponse({"publicado": True, "url": f"/relatorio/{id_exec}"})


# ------------------------------------------------------ rodada no servidor ---
# Roda o fluxo inteiro dentro do servidor, a partir de um formulário no painel.
# Agentes que estão em agentes/GRUPO_X/ rodam aqui (com a GEMINI_API_KEY do
# Render). Os que não estão: ou usam o exemplo no lugar, ou o servidor espera
# o participar.py do grupo rodar no PC dele.

PASTA_AGENTES = BASE / "agentes"
SCRIPTS = {
    1: "GRUPO_3/agente01_publico.py", 2: "GRUPO_1/agente02_concorrencia.py",
    3: "GRUPO_1/agente03_canais.py", 4: "GRUPO_3/agente04_criativo.py",
    5: "GRUPO_2/agente05_performance.py", 6: "GRUPO_2/agente06_financeiro.py",
}
ESPERA_REMOTA_MIN = 45
_RODADAS: dict[str, asyncio.Task] = {}


def _agentes_no_servidor() -> list[int]:
    return [n for n, s in SCRIPTS.items() if (PASTA_AGENTES / s).exists()]


def _estado(id_exec: str) -> dict | None:
    return _ler_json(PASTA_ARMAZENAMENTO / id_exec / "execucao.json") if _id_valido(id_exec) else None


def _salvar_estado(id_exec: str, est: dict) -> None:
    (PASTA_ARMAZENAMENTO / id_exec / "execucao.json").write_text(
        json.dumps(est, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_rodada(id_exec: str, est: dict, texto: str) -> None:
    est["log"].append(f"{datetime.now().strftime('%H:%M:%S')}  {texto}")
    est["log"] = est["log"][-300:]
    _salvar_estado(id_exec, est)


def _gravar_interno(id_exec: str, n: int, mensagem: dict) -> list[str]:
    problemas = _problemas_mensagem(mensagem, n)
    if not problemas:
        (PASTA_ARMAZENAMENTO / id_exec / _arquivo_saida(n)).write_text(
            json.dumps(mensagem, ensure_ascii=False, indent=2), encoding="utf-8")
    return problemas


def _status(n: int, id_exec: str) -> str:
    s = _saida(n, id_exec)
    return s.get("status", "pendente") if s else "pendente"


async def _rodar_script(id_exec: str, n: int, est: dict) -> str:
    env = dict(os.environ)
    env["MCP_URL"] = f"http://127.0.0.1:{int(os.environ.get('PORT', 8000))}/mcp"
    env["PYTHONIOENCODING"] = "utf-8"
    st = "pendente"
    for tentativa in (1, 2):
        _log_rodada(id_exec, est, f"[{n:02d}] rodando {SCRIPTS[n]} (tentativa {tentativa})")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(PASTA_AGENTES / SCRIPTS[n]), "--id", id_exec,
            cwd=str(PASTA_AGENTES), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            saida, _ = await asyncio.wait_for(proc.communicate(), timeout=15 * 60)
        except asyncio.TimeoutError:
            proc.kill()
            saida = b"tempo esgotado (15 min)"
        for linha in saida.decode("utf-8", "replace").splitlines():
            if any(k in linha for k in ("Gemini chamou", "ocupado", "Servidor", "tentativa", "correção",
                                        "Error", "Erro", "erro")):
                _log_rodada(id_exec, est, f"     {linha.strip()[:220]}")
        st = _status(n, id_exec)
        _log_rodada(id_exec, est, f"[{n:02d}] status: {st}")
        if st == "sucesso":
            break
    return st


async def _aguardar_remoto(id_exec: str, n: int, est: dict) -> str:
    _log_rodada(id_exec, est, f"[{n:02d}] {AGENTES[n]['nome']}: aguardando o grupo {AGENTES[n]['grupo']} "
                              f"rodar no PC dele (participar.py {id_exec})")
    inicio = time.time()
    while True:
        st = _status(n, id_exec)
        if st in ("sucesso", "erro"):
            _log_rodada(id_exec, est, f"[{n:02d}] status: {st}")
            return st
        if (time.time() - inicio) / 60 > ESPERA_REMOTA_MIN:
            _log_rodada(id_exec, est, f"[{n:02d}] tempo de espera esgotado")
            return "tempo esgotado"
        await asyncio.sleep(10)


def _leitura_executiva(briefing: dict, saidas: dict) -> dict | None:
    """Resumo executivo, recomendações e riscos em texto (os números vêm das ferramentas)."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None
    dados = {f"{n:02d}_{AGENTES[n]['nome']}": (saidas.get(n) or {}).get("dados") for n in AGENTES}
    prompt = (
        "Você é o diretor de estratégia do Marketing Campaign Commander. Abaixo estão o briefing e as "
        "saídas dos 6 agentes de uma campanha SIMULADA (premissas e números simulados; concorrentes com \"tipo\": \"real\" vieram da internet).\n"
        "Escreva em português, para o cliente, SOMENTE um JSON com:\n"
        '{"resumo_executivo": "4 a 6 frases resumindo a estratégia e o resultado esperado", '
        '"recomendacoes": ["3 a 5 próximos passos práticos"], "riscos": ["2 a 3 riscos da estratégia"]}\n'
        "Use apenas números que aparecem nos dados (cenário realista quando citar resultado). "
        "Não invente números, marcas ou empresas reais. Deixe claro que é uma simulação.\n\n"
        f"BRIEFING:\n{json.dumps(briefing, ensure_ascii=False)}\n\n"
        f"SAÍDAS DOS AGENTES:\n{json.dumps(dados, ensure_ascii=False)}")
    cliente = genai.Client()
    modelos = list(dict.fromkeys([os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
                                  "gemini-3-flash-preview", "gemini-3.8-flash"]))
    for modelo in modelos:
        for espera in (5, 15, None):
            try:
                r = cliente.models.generate_content(
                    model=modelo, contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.4, response_mime_type="application/json"))
                texto = json.loads(r.text)
                if isinstance(texto, dict) and texto.get("resumo_executivo"):
                    return texto
                break
            except Exception as e:
                if getattr(e, "code", None) in (429, 503) and espera:
                    time.sleep(espera)
                    continue
                break
    return None


async def _executar_rodada(id_exec: str, modo: str) -> None:
    import relatorio
    no_servidor = _agentes_no_servidor()
    est = {"estado": "rodando", "modo": modo, "inicio": datetime.now().isoformat(timespec="seconds"),
           "no_servidor": no_servidor, "substitutos": [], "parcial": None, "log": []}
    _salvar_estado(id_exec, est)
    _log_rodada(id_exec, est, "Rodada iniciada no servidor. Agentes no servidor: "
                + (", ".join(f"{n:02d}" for n in no_servidor) or "nenhum"))
    try:
        for n in AGENTES:
            nome = AGENTES[n]["nome"]
            if n in no_servidor:
                st = await _rodar_script(id_exec, n, est)
            elif modo == "exemplo":
                s = _saida(n, ID_EXEMPLO)
                if s is None:
                    st = "erro"
                else:
                    s = dict(s)
                    s["id_execucao"] = id_exec
                    s["observacoes"] = "SUBSTITUTO: saída do EXEMPLO (agente ainda não está no servidor)."
                    problemas = _gravar_interno(id_exec, n, s)
                    if problemas:
                        _log_rodada(id_exec, est, f"[{n:02d}] o exemplo não serve para este briefing: "
                                                  f"{problemas[:2]}")
                        st = "erro"
                    else:
                        est["substitutos"].append(n)
                        _log_rodada(id_exec, est, f"[{n:02d}] {nome}: usando a saída do exemplo no lugar")
                        st = "sucesso"
            else:
                st = await _aguardar_remoto(id_exec, n, est)
            if st != "sucesso":
                est["parcial"] = n
                _log_rodada(id_exec, est, f"Fluxo interrompido no agente {n:02d} ({nome}).")
                break

        v = _validar_execucao(id_exec)
        validacao = ("tudo certo" if v.get("valido") else "; ".join(v.get("problemas") or [])
                     or "incompleta (faltam: " + ", ".join(v.get("pendentes", [])) + ")")
        _log_rodada(id_exec, est, f"Validação cruzada: {validacao}")
        briefing = _briefing(id_exec)
        saidas = {n: _saida(n, id_exec) for n in AGENTES if _saida(n, id_exec)}
        leitura = None
        if not est["parcial"]:
            _log_rodada(id_exec, est, "Pedindo ao Gemini a leitura executiva do relatório...")
            leitura = await asyncio.to_thread(_leitura_executiva, briefing, saidas)
        meta = {"id_execucao": id_exec, "substitutos": est["substitutos"], "validacao": validacao,
                "parcial": est["parcial"]}
        await asyncio.to_thread(relatorio.salvar, PASTA_ARMAZENAMENTO / id_exec, briefing, saidas, meta, leitura)
        est["estado"] = "parcial" if est["parcial"] else "concluida"
        _log_rodada(id_exec, est, "Relatório final pronto.")
    except Exception as e:  # nunca deixa a rodada "rodando" para sempre
        est["estado"] = "erro"
        _log_rodada(id_exec, est, f"Erro inesperado: {type(e).__name__}: {e}")
    finally:
        _RODADAS.pop(id_exec, None)


def _dica(texto: str) -> str:
    """Texto de ajuda embaixo de um campo do formulário (HTML fixo, escrito aqui)."""
    return f"<p class='dica'>{texto}</p>"


def _form_briefing(b: dict, erros: list[str] | None = None, codigo: str = "") -> HTMLResponse:
    def v(k):
        return escape(str(b.get(k, "") if b.get(k) is not None else ""))
    no_servidor = _agentes_no_servidor()
    faltam = [n for n in AGENTES if n not in no_servidor]
    sel = lambda o: " selected" if b.get("objetivo_campanha") == o else ""
    aviso_chave = ("" if os.environ.get("GEMINI_API_KEY") else
                   "<div class='erro-box'>A GEMINI_API_KEY ainda não foi configurada no Render: os agentes "
                   "do servidor não vão conseguir rodar.</div>")
    corpo = (
        "<p><a href='/painel'>← Execuções</a></p><h1>Nova rodada no servidor</h1>"
        "<p class='sub'>Preencha o briefing da empresa que você quiser e o servidor roda o fluxo inteiro "
        "e monta o relatório final.</p>" + aviso_chave
        + ("<div class='erro-box'>" + "<br>".join(escape(e) for e in erros) + "</div>" if erros else "")
        + "<div class='card'><b>Agentes no servidor:</b> "
        + (", ".join(f"{n:02d} {AGENTES[n]['nome']}" for n in no_servidor) or "nenhum")
        + "<br><b>Ainda não estão no servidor:</b> "
        + (", ".join(f"{n:02d} {AGENTES[n]['nome']}" for n in faltam) or "nenhum") + "</div>"
        "<form method='post' action='/painel/novo' class='card'>"
        f"<label>Empresa</label><input name='empresa' required value='{v('empresa')}' placeholder='Ex.: Vitta Fit'>"
        + _dica("O nome da empresa da campanha. Ex.: <b>Vitta Fit</b>, <b>Sabor da Serra</b>.")
        + f"<label>Segmento</label><input name='segmento' value='{v('segmento')}' placeholder='Ex.: moda fitness'>"
        + _dica("Em que mercado ela atua, em poucas palavras. Ex.: <b>moda fitness</b>, <b>bar e eventos</b>, "
                "<b>pizzaria delivery</b>. O agente de Concorrência usa isso para achar os concorrentes.")
        + f"<label>Produto ou serviço</label><textarea name='produto_ou_servico' required placeholder='Ex.: roupas de academia femininas, com loja online'>{v('produto_ou_servico')}</textarea>"
        + _dica("O que a campanha vai divulgar. Ex.: <b>chopp artesanal para festas e eventos</b>.")
        +
        "<div class='duas'><div><label>Objetivo</label><select name='objetivo_campanha'>"
        f"<option value='reconhecimento'{sel('reconhecimento')}>reconhecimento</option>"
        f"<option value='vendas'{sel('vendas')}>vendas</option>"
        f"<option value='leads'{sel('leads')}>leads</option></select>"
        + _dica("<b>reconhecimento</b>: ficar conhecido (seguidores, alcance). <b>vendas</b>: vender mais "
                "(pede o ticket médio). <b>leads</b>: conseguir contatos de interessados (orçamentos, cadastros).")
        + f"</div><div><label>Região</label><input name='regiao' value='{v('regiao')}' placeholder='Ex.: Campinas e região'>"
        + _dica("Onde a campanha vai rodar. Ex.: <b>Campinas e região</b>, <b>todo o Brasil</b>.")
        + f"</div><div><label>Orçamento total (R$)</label><input name='orcamento_total' type='number' min='1' step='1' required value='{v('orcamento_total')}'>"
        + _dica("Quanto a empresa vai investir na campanha inteira. O padrão do trabalho é <b>100000</b>.")
        + f"</div><div><label>Duração (dias)</label><input name='duracao_dias' type='number' min='1' required value='{v('duracao_dias')}'>"
        + _dica("Quantos dias a campanha fica no ar. Ex.: <b>30</b>.")
        + f"</div><div><label>Ticket médio (R$)</label><input name='ticket_medio' type='number' min='0' step='0.01' value='{v('ticket_medio')}'>"
        + _dica("Quanto <b>cada cliente gasta, em média, por compra</b>. Não sabe? Use o <b>preço do produto "
                "mais vendido</b>, ou divida o faturamento do mês pelo número de vendas (ex.: R$ 9.500 ÷ 100 "
                "vendas = <b>95</b>). Obrigatório quando o objetivo é vendas; serve para calcular a receita.")
        + f"</div><div><label>Margem de contribuição (%)</label><input name='margem_contribuicao_percentual' type='number' min='0' max='100' step='0.1' value='{v('margem_contribuicao_percentual')}'>"
        + _dica("Quanto <b>sobra de cada venda</b> depois de pagar o que custou para fazer ou comprar o "
                "produto, em %. Conta: (preço − custo) ÷ preço × 100. Ex.: o produto vende por R$ 95 e custa "
                "R$ 43 → sobram R$ 52 → 52 ÷ 95 ≈ <b>55</b>. Não sabe? Use um valor típico: <b>30</b> para "
                "revenda, <b>50</b> a <b>60</b> para produto artesanal, <b>70</b> para serviço. Pode deixar "
                "em branco: o relatório só não calcula o ROI.")
        + "</div></div>"
        + f"<label>Observações</label><textarea name='observacoes' placeholder='Ex.: marca nova, tem 3 mil seguidores no Instagram'>{v('observacoes')}</textarea>"
        + _dica("Qualquer detalhe que ajude os agentes: situação atual, público que já compra, o que "
                "a empresa quer evitar. Ex.: <b>marca nova, tem 3 mil seguidores no Instagram</b>.")
        + ((
        "<label>Agentes que ainda não estão no servidor</label><select name='modo'>"
        "<option value='esperar'>Esperar os grupos rodarem no PC deles (participar.py)</option>"
        "<option value='exemplo'>Usar uma saída de exemplo no lugar (só para teste)</option></select>"
        + _dica("Só aparece quando falta algum agente no servidor.")) if faltam else "")
        + (f"<label>Código de acesso</label><input name='codigo' type='password' value='{escape(codigo)}' required>"
           if os.environ.get("CODIGO_ACESSO") else "")
        + "<p><button class='botao' type='submit' style='border:0;cursor:pointer'>Rodar</button></p></form>")
    return _pagina("Nova rodada", corpo)


@mcp.custom_route("/painel/novo", methods=["GET"])
async def nova_rodada_form(request: Request) -> HTMLResponse:
    return _form_briefing({"objetivo_campanha": "reconhecimento", "orcamento_total": 100000,
                           "duracao_dias": 30})


@mcp.custom_route("/painel/novo", methods=["POST"])
async def nova_rodada(request: Request):
    form = await request.form()

    def num(campo, tipo=float):
        txt = str(form.get(campo, "")).strip().replace(",", ".")
        if not txt:
            return None
        try:
            return tipo(float(txt))
        except ValueError:
            return None

    b = {
        "empresa": str(form.get("empresa", "")).strip(),
        "segmento": str(form.get("segmento", "")).strip(),
        "produto_ou_servico": str(form.get("produto_ou_servico", "")).strip(),
        "objetivo_campanha": str(form.get("objetivo_campanha", "")).strip(),
        "orcamento_total": num("orcamento_total", int),
        "moeda": "BRL",
        "duracao_dias": num("duracao_dias", int),
        "regiao": str(form.get("regiao", "")).strip(),
        "ticket_medio": num("ticket_medio"),
        "margem_contribuicao_percentual": num("margem_contribuicao_percentual"),
        "concorrentes_conhecidos": [],
        "observacoes": str(form.get("observacoes", "")).strip(),
    }
    codigo = str(form.get("codigo", ""))
    modo = "exemplo" if form.get("modo") == "exemplo" else "esperar"
    erros = _problemas_briefing(b)
    if os.environ.get("CODIGO_ACESSO") and codigo != os.environ["CODIGO_ACESSO"]:
        erros.append("Código de acesso incorreto.")
    if _agentes_no_servidor() and not os.environ.get("GEMINI_API_KEY"):
        erros.append("A GEMINI_API_KEY não está configurada no Render.")
    if any(not t.done() for t in _RODADAS.values()):
        erros.append("Já existe uma rodada em andamento no servidor. Espere ela terminar.")
    if erros:
        return _form_briefing(b, erros, codigo)

    # mesma forma de gravar que o exemplo usa (números inteiros onde der)
    for k in ("ticket_medio", "margem_contribuicao_percentual"):
        if isinstance(b[k], float) and b[k].is_integer():
            b[k] = int(b[k])
    id_exec = datetime.now().strftime("EXEC-%Y%m%d-%H%M%S")
    pasta = PASTA_ARMAZENAMENTO / id_exec
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "briefing.json").write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
    _RODADAS[id_exec] = asyncio.create_task(_executar_rodada(id_exec, modo))
    return RedirectResponse(f"/painel/{id_exec}", status_code=303)


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 8000))
    mcp.run(transport="http", host="0.0.0.0", port=porta, show_banner=False)
