# Servidor MCP — Marketing Campaign Commander

Caixa de ferramentas central do sistema multiagente do trabalho. Fica
hospedado num link único, e todos os agentes dos 3 grupos se conectam nele:

```
https://mcp-campaign-commander.onrender.com/mcp
```

Quando um agente se conecta, ele recebe a lista de ferramentas e pode ler as
regras do contrato e a **ficha do seu papel**, com o formato exato da saída.

## O que vai neste repositório

- **Vai:** o servidor, as regras do contrato, as bases fictícias e o exemplo
  oficial.
- **Não vai:** os agentes. Eles ficam com cada grupo. Cada agente só precisa
  do link do servidor.
- **Nunca vai:** chave do Gemini.

```
mcp-server/
├── servidor_mcp.py              o servidor (22 ferramentas)
├── regras/contrato.md           resumo das regras (ler_regras_contrato)
├── dados/
│   ├── concorrentes.json        base fictícia de concorrentes (reserva da busca)
│   └── premissas_simulacao.json premissas por canal e regras de distribuição
│                                (RASCUNHO, o Grupo 2 valida)
├── exemplos/                    exemplo oficial (id EXEMPLO): Lume Ateliê de
│                                Aromas, briefing + saídas dos 6 agentes
├── testar_servidor.py           testa o servidor sem usar o Gemini
├── requirements.txt
└── render.yaml                  configuração do Render
```

## Ferramentas

| Para quem | Ferramenta | O que faz |
|---|---|---|
| Todos | `ler_regras_contrato(secao)` | Regras do contrato, inteiras ou por seção |
| | `ler_ficha_agente(numero)` | Missão, o que lê, ferramentas e formato exato da saída |
| | `listar_canais_suportados` | Lista fechada de canais |
| | `ler_briefing(id)` | Briefing da execução |
| | `ler_saida_agente(numero, id)` | Saída de outro agente |
| | `verificar_saida(numero, mensagem)` | Confere formato e regras sem gravar |
| | `ler_dados(nome)` | Atalho para as bases fictícias |
| 02 Concorrência | `buscar_concorrentes_web(consultas)` | Busca concorrentes reais na internet (Tavily) e devolve título, link e trecho |
| | `ler_concorrentes(segmento)` | Reserva: base fictícia filtrada pelo segmento |
| 03 Canais | `ler_premissas_simulacao` | Custos e taxas de referência por canal |
| | `validar_canais(canais)` | Lista fechada e de 2 a 5 canais |
| 04 Criativo | `verificar_mensagens_criativo` | Mensagem para cada canal e limites de texto |
| 05 Simulador | `simular_canais(canais, investimento)` | KPIs por canal nos 3 cenários |
| 06 Financeiro | `validar_distribuicao` | Percentuais contra as regras de distribuição |
| | `calcular_distribuicao_orcamento` | % em R$, fechando o orçamento exato |
| | `projetar_resultados(valores)` | Totais, receita, ROAS e ROI por cenário |
| | `calcular_indicadores` | ROAS e ROI avulsos |
| Orquestrador | `registrar_briefing(briefing)` | Abre a execução e devolve o id |
| | `validar_briefing` | Confere o briefing |
| | `listar_execucoes` | Execuções e agentes concluídos |
| | `validar_execucao(id)` | Validações cruzadas do fluxo |
| Script do agente | `gravar_saida(id, numero, mensagem)` | Grava a saída (o modelo não usa) |

## Exemplo oficial (id `EXEMPLO`)

**Lume Ateliê de Aromas**: empresa fictícia de velas, incensos, difusores e
sachês artesanais de Campinas, que quer aumentar a popularidade no Instagram
(objetivo: reconhecimento), com R$ 100 mil por 30 dias. O briefing e as saídas
dos 6 agentes ficam fixos em `exemplos/` e nunca somem. Testes com o id
`EXEMPLO` são conferidos, mas não gravados, para não alterar o exemplo.

Os números do Simulador (05) e do Financeiro (06) foram calculados pelas
próprias ferramentas do servidor, com as premissas em rascunho.

## Rodada no servidor (sem precisar de PC)

Em `/painel/novo` há um formulário de briefing. Ao clicar em **Rodar**, o
servidor abre a execução e roda o fluxo inteiro sozinho:

- agentes que estão em `agentes/GRUPO_X/` rodam dentro do servidor;
- os que ainda não estão: usam a saída do exemplo no lugar (só com o
  briefing da Lume) **ou** o servidor espera o grupo rodar o `participar.py`
  no PC dele, conforme a opção escolhida no formulário;
- no fim, o relatório final fica em `/relatorio/EXEC-...`.

Configuração no Render (aba **Environment** do serviço):
- `GEMINI_API_KEY`: chave do Gemini usada pelos agentes do servidor;
- `CODIGO_ACESSO`: senha pedida no formulário (evita que qualquer pessoa
  com o link gaste a cota do Gemini).
- `TAVILY_API_KEY`: chave do Tavily, usada por `buscar_concorrentes_web`
  (plano grátis: 1.000 buscas por mês). Sem ela, o Agente 02 usa a base
  fictícia de concorrentes.

Para colocar o agente de outro grupo no servidor, suba o arquivo em
`agentes/GRUPO_X/` com o nome do contrato (ex.: `agentes/GRUPO_3/agente01_publico.py`).

## Atualizar

Edite ou suba o arquivo no GitHub. O Render publica sozinho a cada commit
(uns 2 minutos). Quando o Grupo 2 validar as premissas, é só substituir
`dados/premissas_simulacao.json`.

## Limites do plano grátis do Render

- O servidor dorme depois de 15 minutos sem uso e leva cerca de 1 minuto para
  acordar. Antes de apresentar, abra o link no navegador.
- As saídas gravadas em execuções reais (`armazenamento/`) somem quando o
  servidor dorme ou reinicia. Por isso o Orquestrador roda o fluxo todo de
  uma vez, e cada agente guarda uma cópia local em `saidas/`.

## Testar

```
pip install -r requirements.txt
python testar_servidor.py https://mcp-campaign-commander.onrender.com/mcp
```

Para rodar localmente: `python servidor_mcp.py` (link `http://localhost:8000/mcp`).
