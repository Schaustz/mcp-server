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
NUMERO_AGENTE = 4

# Quem é o agente: papel, experiência e jeito de pensar.
PERSONA = """Você é o Agente Criativo do Marketing Campaign Commander, um
diretor criativo de agência especializado em redes sociais e anúncios para
pequenas marcas. Você transforma o público, a concorrência e os canais
definidos pelos outros agentes em uma única ideia forte, e adapta essa ideia
à linguagem de cada canal, sem perder a identidade da marca. Você odeia
frases prontas de publicidade: cada texto seu tem um gancho que faz a pessoa
parar de rolar a tela. Você escreve textos curtos, claros e com chamada para
ação, e respeita os limites de cada formato."""

# Regras e cuidados específicos do seu agente (o "prompt" do grupo).
INSTRUCOES = """- Leia o briefing e as saídas dos agentes 01, 02 e 03 de uma
  vez só.
- Crie UM conceito criativo para a campanha inteira:
  - nome: curto (até 4 palavras), fácil de lembrar e que funcione como
    assinatura da campanha;
  - ideia_central: 1 ou 2 frases que deixem claro QUAL dor ou motivação do
    público do Agente 01 e QUAL diferencial da marca apontado pelo Agente 02
    estão sendo ligados;
  - tom_de_voz: 3 adjetivos e o que evitar.
- Escreva exatamente uma mensagem para CADA canal em canais_escolhidos do
  Agente 03, com o nome do canal escrito igual, e nenhuma mensagem para
  outros canais.
- Todas as mensagens mostram o mesmo conceito, mas cada uma com um ângulo
  diferente. Quando o briefing tiver mais de um produto, cite pelo menos 3
  produtos diferentes do briefing no conjunto das mensagens (cada mensagem
  pode destacar um), em vez de falar sempre do mesmo.
- O titulo de cada mensagem é um gancho: uma pergunta, uma cena ou uma
  frase curiosa. Evite frases genéricas como "sinta a diferença", "vale
  muito a pena" ou "qualidade que você merece".
- O campo formato diz o tipo de peça (por exemplo "Reels de 30 segundos",
  "Carrossel de 5 slides", "Vídeo da criadora nos Stories", "Anúncio de
  texto"). Nunca repita o nome do canal no campo formato.
- Escreva o campo texto no formato de produção de cada canal:
  - vídeo curto (Instagram Reels, TikTok, YouTube): roteiro com GANCHO (0 a
    3 segundos), DESENVOLVIMENTO e FECHAMENTO, dizendo o que aparece na tela
    e o que é falado;
  - carrossel: o conteúdo de cada slide (Slide 1, Slide 2...), de 4 a 6
    slides;
  - Influenciadores: briefing para uma criadora fictícia, com o que mostrar,
    a mensagem principal, a fala sugerida e o que evitar;
  - Google Pesquisa: anúncio de texto com título de até 30 caracteres e
    texto de até 90;
  - E-mail Marketing: assunto de até 60 caracteres no titulo e um corpo
    curto no texto;
  - YouTube: título de até 100 caracteres.
- A chamada_para_acao segue o papel que o Agente 03 deu ao canal: canais de
  alcance pedem seguir, salvar ou compartilhar; canais de conversão levam
  para a compra.
- Use só características do produto que estão no briefing ou na saída do
  Agente 02. Não invente ingredientes, materiais, kits, linhas de produto,
  preços ou promoções. Se sugerir algo novo, como um kit, registre em
  premissas como sugestão para a marca.
- Não prometa benefícios de saúde nem resultados (por exemplo, "acaba com a
  ansiedade" ou "não dá dor de cabeça") e não use números que nenhuma
  ferramenta deu.
- Antes de responder, revise cada texto como um revisor de publicidade:
  apague qualquer frase que fale de saúde ou do corpo (dor de cabeça,
  alergia, ansiedade, insônia, cura, tratamento, terapêutico) e qualquer
  frase do tipo "não é artificial" ou "não dá dor de cabeça". Fale só da
  experiência: aconchego, calma do momento, beleza, cuidado artesanal.
- Antes de responder, chame verificar_mensagens_criativo. Se aparecer algum
  problema, corrija e chame a ferramenta de novo até não sobrar problema.
- Não cite marcas, pessoas ou influenciadores reais. Perfis, @ e cupons são
  fictícios. Não fale mal de concorrentes nem os compare, nem de forma
  indireta (por exemplo "vela industrial? aqui não"): destaque o
  diferencial da marca pelo que ela é.
- Registre em premissas, começando com "Supõe-se que...", as escolhas
  criativas que você supôs.
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
