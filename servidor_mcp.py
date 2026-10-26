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
- 02 Concorr.: ler_concorrentes
- 03 Canais:   validar_canais, ler_premissas_simulacao (custos de referência)
- 04 Criativo: verificar_mensagens_criativo
- 05 Simul.:   ler_premissas_simulacao, simular_canais
- 06 Financ.:  validar_distribuicao, calcular_distribuicao_orcamento,
               projetar_resultados, calcular_indicadores
- Orquestr.:   registrar_briefing, validar_briefing, listar_execucoes,
               validar_execucao, gravar_saida (usada pelo script de cada agente)
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
        "le": ["briefing", "saída 01", "dados concorrentes"],
        "entrega_para": "agente03_canais",
        "missao": "Mostrar COMO está o mercado: concorrentes, lacunas e diferenciais.",
        "ferramentas_recomendadas": ["ler_briefing", "ler_saida_agente", "ler_concorrentes"],
        "campos_obrigatorios": ["concorrentes_analisados", "lacunas_de_mercado",
                                "diferenciais_sugeridos", "canais_mais_disputados"],
        "formato_dados": {
            "concorrentes_analisados": [{"nome": "", "tipo": "simulado", "posicionamento": "",
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
                   "o agente interpreta e ranqueia, nunca calcula."),
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
                   "nos 3 cenários. Percentuais vêm do agente; valores e KPIs vêm das ferramentas."),
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
Todos os dados são fictícios."""

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
            if isinstance(c, dict) and c.get("tipo") != "simulado":
                problemas.append(f"concorrente {c.get('nome')} precisa de \"tipo\": \"simulado\"")

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
def gravar_saida(id_execucao: str, numero_agente: int, mensagem: dict) -> dict:
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
    """[02 Concorrência] Retorna a base fictícia de concorrentes. Com
    'segmento' (ex.: o segmento do briefing), filtra pelos concorrentes
    daquele segmento. Todos são simulados, nenhum é real."""
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
    tiver ticket médio). Simulação — não representa resultado real."""
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
    Simulação — não representa resultado real."""
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
    })


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 8000))
    mcp.run(transport="http", host="0.0.0.0", port=porta, show_banner=False)
