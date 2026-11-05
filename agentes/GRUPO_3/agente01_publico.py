"""
MODELO DE AGENTE — Marketing Campaign Commander
===============================================

Copie este arquivo para a pasta do seu grupo com o nome do contrato
(ex.: GRUPO_3/agente01_publico.py) e troque SÓ o bloco CONFIGURAÇÃO DO AGENTE:
NUMERO_AGENTE, PERSONA e INSTRUCOES. O resto é igual para todos.

Rodar a partir de 01_PROJETO:
    python GRUPO_X/agenteNN_nome.py                    (teste no EXEMPLO)
    python GRUPO_X/agenteNN_nome.py --id EXEC-...      (Orquestrador)
    python GRUPO_X/agenteNN_nome.py --pedido "..."     (instrução extra)

Variáveis de ambiente: GEMINI_API_KEY (obrigatória), GEMINI_MODEL e MCP_URL
(opcionais).
"""

import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from fastmcp import Client
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# ======================= CONFIGURAÇÃO DO AGENTE (troque aqui) ===============

# 1 Público, 2 Concorrência, 3 Canais, 4 Criativo, 5 Simulador, 6 Financeiro.
# O número define a ficha que vem do servidor: missão, o que ler, ferramentas
# recomendadas e o formato exato da saída. Não precisa escrever o formato aqui.
NUMERO_AGENTE = 1

# Quem é o agente: papel, experiência e jeito de pensar.
PERSONA = """Você é o Agente de Público do Marketing Campaign Commander, um
estrategista de pesquisa de consumidor com experiência em pequenos negócios e
marcas locais no Brasil. Você pensa como quem já entrevistou muitos clientes:
parte do produto, do preço e do objetivo da campanha para descrever pessoas
reais e concretas, nunca perfis genéricos. Você escreve de um jeito que faz a
equipe enxergar o cliente, como se ele estivesse na sala. Você sabe que o seu
trabalho é a base de todo o fluxo: o Agente de Canais escolhe onde anunciar a
partir do que você escreve, e o Agente Criativo escreve as mensagens a partir
das dores e motivações que você define."""

# Regras e cuidados específicos do seu agente (o "prompt" do grupo).
INSTRUCOES = """- Chame também listar_canais_suportados e use exatamente esses
  nomes de canais quando falar de plataformas.
- Defina o público prioritário a partir do produto, do segmento, da região, do
  ticket médio, do objetivo da campanha e das observações do briefing.
- No campo regiao, copie a região do briefing por inteiro, palavra por
  palavra, sem resumir nem cortar nenhuma parte.
- Preencha TODOS os campos do formato. Nenhum texto vazio e nenhuma lista
  vazia. Listas de interesses, dores e motivações com 3 a 5 itens cada.
- Dê ao público prioritário um nome marcante, que crie uma imagem na cabeça
  (por exemplo, "A Caçadora de Pequenos Luxos"), e não um rótulo genérico.
- Em descricao, faça um retrato vivo em 2 ou 3 frases: mostre um momento
  concreto do dia dessa pessoa em que o produto faria sentido.
- Escreva as dores e as motivações em primeira pessoa, como frases que essa
  pessoa diria de verdade (por exemplo: Chego em casa cansada e nada ali me
  faz desacelerar). Elas devem ter ligação com o objetivo da campanha.
- comportamento_digital é o campo mais importante. Descreva a jornada em três
  momentos, citando pelo menos 3 canais diferentes da lista oficial, com o
  nome exato:
  1. DESCOBRE: onde conhece marcas novas e que formato prende a atenção dela
     (vídeo curto, carrossel, bastidor, indicação);
  2. PESQUISA: onde confere preço, avaliações e reputação antes de comprar;
  3. DECIDE: onde fecha a compra ou o que faz ela comprar naquele momento.
  Diga também em quem ela confia e que tipo de conteúdo ela ignora. Nunca
  escreva só "usa redes sociais" e nunca cite um canal só.
- Antes de responder, conte quantos canais da lista oficial aparecem no
  comportamento_digital (link na bio, site ou loja online não contam como
  canal). Se forem menos de 3, reescreva o campo.
- Crie de 1 a 3 públicos secundários, diferentes entre si e do prioritário,
  cada um com um motivo diferente para entrar na campanha. Em por_que_importa,
  explique como ele ajuda o objetivo da campanha.
- Escreva de 3 a 5 insights no formato "observação sobre o público ->
  oportunidade para a campanha". Pelo menos um deve ser surpreendente, algo
  que a equipe não perceberia de primeira. Não escolha canais nem defina
  orçamento: isso é papel de outros agentes.
- Não invente pesquisas, estatísticas, porcentagens ou números de mercado. Não
  cite marcas, pessoas ou influenciadores reais.
- Nos campos do público (faixa_etaria, genero_predominante, regiao etc.),
  escreva só o valor, por exemplo "28 a 42 anos" ou "Feminino". As palavras
  hipótese e "Supõe-se" ficam apenas em premissas.
- Faixa etária, gênero predominante e hábitos são hipóteses: registre cada
  uma em premissas escrita como hipótese (por exemplo, "Supõe-se que..."),
  nunca como se fosse um dado de mercado comprovado.
- Todos os dados são fictícios e simulados."""

# ======================= daqui para baixo é igual para todos ================

RAIZ = Path(__file__).resolve().parent.parent          # 01_PROJETO
MCP_URL = os.environ.get("MCP_URL", "https://mcp-campaign-commander.onrender.com/mcp")
MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
# Se o modelo principal estiver sobrecarregado, o agente passa para o próximo
# da fila (todos grátis). Repetidos são ignorados.
MODELOS = list(dict.fromkeys([MODELO, "gemini-3-flash-preview", "gemini-3.8-flash"]))
MAX_RODADAS = 12
ESPERAS_SOBRECARGA = [5, 15]  # segundos, antes de trocar de modelo
MAX_TENTATIVAS = 2            # erros inesperados (ex.: rede): tenta mais uma vez
SO_SCRIPT = {"gravar_saida", "registrar_briefing"}  # o Gemini não recebe estas

TAREFA = """Execução: {id_execucao}
Você é o agente {numero:02d} ({nome}). Sua missão: {missao}

Passos:
1. Chame ler_regras_contrato e ler_briefing(id_execucao="{id_execucao}").
2. Leia as saídas dos agentes anteriores com ler_saida_agente(numero_agente=N,
   id_execucao="{id_execucao}"). Você lê: {le}.
3. Use as ferramentas recomendadas para o seu papel: {ferramentas}.
Peça várias ferramentas DE UMA VEZ na mesma resposta sempre que der.

Instruções específicas:
{instrucoes}
{pedido}
Contas (somas, porcentagens, KPIs, dinheiro) são feitas SÓ pelas ferramentas.
Nunca invente números que as ferramentas não deram.

Responda SOMENTE com um JSON válido, sem texto antes ou depois, com os campos
abaixo (o que é texto entre aspas é só modelo). Campos obrigatórios:
{obrigatorios}. Inclua também "premissas": lista com as suposições que você fez.
{formato}"""


class ModeloSobrecarregado(Exception):
    """O Google continuou respondendo 503/429 depois das esperas."""


def extrair_json(texto: str) -> dict:
    """Aceita a resposta com ou sem bloco ```json."""
    texto = (texto or "").strip()
    bloco = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    if bloco:
        texto = bloco.group(1)
    dados = json.loads(texto)
    if not isinstance(dados, dict):
        raise ValueError("a resposta precisa ser um objeto JSON")
    return dados


def resultado_da_ferramenta(r) -> dict:
    """Converte o retorno de uma ferramenta MCP num dict."""
    if r.is_error:
        return {"erro": r.content[0].text if r.content else "erro na ferramenta"}
    if r.structured_content is not None:
        return r.structured_content
    texto = r.content[0].text if r.content else ""
    try:
        return {"resultado": json.loads(texto)}
    except json.JSONDecodeError:
        return {"resultado": texto}


async def ferramenta(mcp: Client, nome: str, args: dict) -> dict:
    return resultado_da_ferramenta(await mcp.call_tool(nome, args, raise_on_error=False))


async def perguntar_ao_gemini(gemini, modelo, historico, config):
    """Chama o Gemini; se estiver sobrecarregado (503/429), espera e repete."""
    for espera in ESPERAS_SOBRECARGA + [None]:
        try:
            return await gemini.aio.models.generate_content(
                model=modelo, contents=historico, config=config)
        except genai_errors.APIError as e:
            if e.code not in (429, 503):
                raise
            if espera is None:
                raise ModeloSobrecarregado(f"{modelo} ocupado (erro {e.code})") from e
            print(f"  (Gemini ocupado, erro {e.code}; tentando de novo em {espera}s)")
            await asyncio.sleep(espera)


async def chamar_gemini(mcp, id_execucao, modelo, ficha, pedido) -> dict:
    """Loop de ferramentas: o Gemini pede, o script executa no servidor MCP e
    devolve o resultado, até o Gemini responder o JSON final."""
    gemini = genai.Client()  # lê GEMINI_API_KEY do ambiente
    ferramentas = [f for f in await mcp.list_tools() if f.name not in SO_SCRIPT]
    config = types.GenerateContentConfig(
        system_instruction=PERSONA,
        temperature=0.4,
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=f.name,
                description=f.description,
                parameters_json_schema=getattr(f, "input_schema", None) or f.inputSchema,
            )
            for f in ferramentas
        ])],
    )
    tarefa = TAREFA.format(
        id_execucao=id_execucao, numero=NUMERO_AGENTE, nome=ficha["nome"],
        missao=ficha["missao"], le=", ".join(ficha["le"]),
        ferramentas=", ".join(ficha["ferramentas_recomendadas"]),
        instrucoes=INSTRUCOES,
        pedido=f"\nPedido extra de quem está rodando: {pedido}\n" if pedido else "",
        obrigatorios=", ".join(ficha["campos_obrigatorios"]),
        formato=json.dumps(ficha["formato_dados"], ensure_ascii=False, indent=2),
    )
    historico = [types.Content(role="user", parts=[types.Part(text=tarefa)])]

    correcoes = 1  # contrato: resposta inválida -> uma nova chance
    for _ in range(MAX_RODADAS):
        resposta = await perguntar_ao_gemini(gemini, modelo, historico, config)
        chamadas = resposta.function_calls
        if not chamadas:
            # Resposta final: confere o JSON e o formato no servidor
            try:
                dados = extrair_json(resposta.text)
                mensagem = montar_mensagem(id_execucao, ficha, "sucesso", dados, [])
                v = await ferramenta(mcp, "verificar_saida",
                                     {"numero_agente": NUMERO_AGENTE, "mensagem": mensagem})
                problemas = [] if v.get("valido") else v.get("problemas", [str(v)])
            except ValueError as e:  # inclui JSON inválido
                problemas = [f"JSON inválido: {e}"]
            if not problemas:
                return dados
            if correcoes == 0:
                raise ValueError(f"saída fora do formato: {problemas}")
            correcoes -= 1
            print(f"  (resposta fora do formato, pedindo correção: {problemas})")
            historico.append(resposta.candidates[0].content)
            historico.append(types.Content(role="user", parts=[types.Part(text=(
                "Sua resposta não passou na verificação do contrato. Problemas: "
                f"{problemas}. Corrija e responda de novo SOMENTE com o JSON completo."))]))
            continue

        historico.append(resposta.candidates[0].content)
        partes = []
        for chamada in chamadas:
            args = dict(chamada.args or {})
            print(f"  -> Gemini chamou {chamada.name}({args})")
            partes.append(types.Part.from_function_response(
                name=chamada.name, response=await ferramenta(mcp, chamada.name, args)))
        historico.append(types.Content(role="user", parts=partes))

    raise RuntimeError(f"Gemini não terminou em {MAX_RODADAS} rodadas")


def montar_mensagem(id_execucao, ficha, status, dados, erros) -> dict:
    dados = dict(dados or {})
    premissas = dados.pop("premissas", [])
    if not isinstance(premissas, list):
        premissas = [str(premissas)]
    return {
        "id_execucao": id_execucao,
        "agente_origem": ficha["chave"],
        "agente_destino": ficha["entrega_para"],
        "data_hora": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "entradas_usadas": ficha["le"],
        "dados": dados,
        "premissas": premissas,
        "erros": erros,
        "observacoes": "",
    }


async def entregar(mcp: Client, mensagem: dict, ficha: dict) -> None:
    """Grava no servidor (mesa compartilhada) e guarda cópia local."""
    r = await ferramenta(mcp, "gravar_saida", {
        "id_execucao": mensagem["id_execucao"],
        "numero_agente": NUMERO_AGENTE,
        "mensagem": mensagem,
    })
    if r.get("gravado"):
        print(f"Servidor: saída gravada em {r['arquivo']}")
    elif r.get("teste_aprovado"):
        print(f"Servidor: {r['aviso']}")
    else:
        print(f"Servidor recusou a saída: {r.get('problemas') or r}")

    pasta = RAIZ / "saidas"
    pasta.mkdir(exist_ok=True)
    arquivo = pasta / ficha["arquivo_saida"]
    arquivo.write_text(json.dumps(mensagem, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Cópia local: {arquivo.relative_to(RAIZ)}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default="EXEMPLO",
                        help="id_execucao vindo do Orquestrador (padrão: EXEMPLO)")
    parser.add_argument("--pedido", default="",
                        help="instrução extra para esta execução")
    args = parser.parse_args()
    id_execucao = args.id

    print(f"Conectando em {MCP_URL} (no plano grátis, a 1ª conexão pode levar ~1 min)")
    # timeout alto porque o servidor grátis "dorme" e demora para acordar
    async with Client(MCP_URL, timeout=120, init_timeout=120) as mcp:
        if NUMERO_AGENTE not in range(1, 7):
            raise SystemExit("Defina NUMERO_AGENTE (1 a 6) no bloco CONFIGURAÇÃO DO AGENTE")
        ficha = await ferramenta(mcp, "ler_ficha_agente", {"numero_agente": NUMERO_AGENTE})
        if "erro" in ficha:
            raise SystemExit(f"Ficha do agente não encontrada: {ficha['erro']}")
        print(f"Agente {NUMERO_AGENTE:02d} — {ficha['nome']} | execução {id_execucao}")

        erros, fila, tentativas = [], list(MODELOS), 0
        while fila and tentativas < MAX_TENTATIVAS:
            modelo = fila[0]
            print(f"Usando o modelo {modelo}")
            try:
                dados = await chamar_gemini(mcp, id_execucao, modelo, ficha, args.pedido)
                await entregar(mcp, montar_mensagem(id_execucao, ficha, "sucesso", dados, []), ficha)
                return
            except ModeloSobrecarregado as e:
                # Sobrecarga do Google não conta como tentativa: troca de modelo
                erros.append(str(e))
                print(f"  {e}; trocando de modelo")
                fila.pop(0)
            except Exception as e:
                tentativas += 1
                erros.append(f"tentativa {tentativas} ({modelo}): {type(e).__name__}: {e}")
                print(erros[-1])

        await entregar(mcp, montar_mensagem(id_execucao, ficha, "erro", {}, erros), ficha)


if __name__ == "__main__":
    asyncio.run(main())
