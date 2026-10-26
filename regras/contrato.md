# Regras do Contrato Base dos Agentes — Marketing Campaign Commander

Resumo das regras do Contrato Base dos Agentes (v1.2), servido pelo servidor MCP
para qualquer agente, novo ou antigo, ler antes de trabalhar. O documento
completo fica no Google Drive, em 00_DOCUMENTACAO.

## Visão geral
- Uma empresa fictícia tem R$ 100 mil para uma campanha. O sistema analisa
  público, concorrência e canais, cria as mensagens, simula a performance e
  distribui o orçamento, entregando um plano final com KPIs projetados.
- É um SIMULADOR de planejamento: nenhum anúncio é publicado, nenhum dinheiro é
  gasto e nenhum dado real de plataforma é usado.
- IA: somente Gemini (plano gratuito). Linguagem: Python.

## Fluxo
briefing -> Orquestrador valida -> 01 Público -> 02 Concorrência -> 03 Canais
-> 04 Criativo -> 05 Simulador de Performance -> 06 Financeiro -> Orquestrador
-> plano final.
- 01 Público: QUEM é o cliente.
- 02 Concorrência: COMO está o mercado.
- 03 Canais: ONDE anunciar.
- 04 Criativo: O QUE dizer em cada canal.
- 05 Simulador: QUANTO cada canal tende a render.
- 06 Financeiro: QUANTO DINHEIRO vai para cada canal.
- Cada agente pode LER qualquer saída anterior, mas só GRAVA a própria.

## Comunicação entre agentes
- Os agentes nunca chamam uns aos outros. Cada um grava sua saída no servidor
  MCP (ferramenta gravar_saida) e o próximo lê de lá (ler_saida_agente).
- Toda saída pertence a um id_execucao. O Orquestrador cria o id ao registrar o
  briefing e repassa a todos. Agente rodando sozinho usa o id EXEMPLO.
- O servidor hospedado não guarda arquivos para sempre: cada agente também
  grava uma cópia local em saidas/ (registro oficial do trabalho).

## Formato padrão de mensagem
Todo agente grava exatamente estes campos:
id_execucao, agente_origem, agente_destino, data_hora, status
("sucesso" ou "erro"), entradas_usadas (lista), dados (objeto),
premissas (lista), erros (lista), observacoes (texto).
- dados: conteúdo específico de cada agente.
- premissas: suposições que o agente fez.
- erros: motivo do erro quando status = "erro".

## Regras de integração
- Cada agente roda sozinho: lê as entradas, monta o prompt, chama o Gemini,
  valida a resposta, grava a saída e termina.
- O prompt sempre pede resposta SOMENTE em JSON. O script valida o JSON; se vier
  inválido, tenta mais uma vez; se falhar de novo, grava status "erro".
- Quem grava a saída é o SCRIPT, depois de validar. O modelo nunca grava direto.
- Chave do Gemini nas variáveis GEMINI_API_KEY e GEMINI_MODEL, nunca no Drive
  nem no GitHub. O link do servidor fica em MCP_URL.
- Um script nunca importa nem chama o código de outro grupo.

## Regras de dados
- Contas (somas, porcentagens, KPIs, distribuição de dinheiro) sempre em Python
  (ferramentas do servidor), nunca no Gemini.
- Nenhum dado pode ser apresentado como real: concorrentes e premissas são
  fictícios e marcados com "tipo": "simulado".
- Receita não é lucro, e ROAS não é ROI.
- O servidor recalcula os números do Simulador (05) e do Financeiro (06) e
  recusa a saída se algum número não bater com o das ferramentas.
- O plano final separa: dados do briefing, dados simulados, premissas e
  resultados calculados.

## Canais
Lista fechada, nomes escritos exatamente assim: Instagram, Facebook,
Google Pesquisa, YouTube, TikTok, LinkedIn, E-mail Marketing, Influenciadores.
Nenhum agente pode sugerir canal fora desta lista.

## Briefing
- Obrigatórios: empresa, produto_ou_servico, objetivo_campanha
  (vendas | leads | reconhecimento), orcamento_total, duracao_dias.
- ticket_medio: obrigatório quando o objetivo é "vendas".
- margem_contribuicao_percentual: opcional. Sem ela, calcula ROAS mas NÃO ROI.

## Orquestrador
1. Registra o briefing (registrar_briefing), que valida e cria o id_execucao.
2. Executa os agentes 01 a 06 em ordem.
3. Depois de cada agente confere se a saída existe e se status = "sucesso".
   Se der erro, tenta mais uma vez; se continuar, gera relatório parcial.
4. Validações cruzadas: canais do 03 na lista; Criativo com mensagem para cada
   canal escolhido; soma do Financeiro igual ao orcamento_total.
5. Gera o plano final (json e md).

## Plano final
Resumo; público prioritário; concorrência e diferenciais; conceito criativo e
mensagens por canal; canais escolhidos; distribuição do orçamento; KPIs nos
cenários pessimista, realista e otimista; receita, ROAS e ROI (se houver
margem); riscos; premissas e limitações, com o aviso
"Simulação — não representa resultado real".

## Ferramentas por agente
- Todos: ler_regras_contrato, ler_ficha_agente (traz o formato exato da saída),
  listar_canais_suportados, ler_briefing, ler_saida_agente, verificar_saida.
- 01 Público: usa as ferramentas de todos.
- 02 Concorrência: ler_concorrentes (filtra pelo segmento do briefing).
- 03 Canais: ler_premissas_simulacao (custos de referência) e validar_canais
  (2 a 5 canais da lista fechada).
- 04 Criativo: verificar_mensagens_criativo (uma mensagem por canal escolhido
  e limites de texto de referência).
- 05 Simulador: ler_premissas_simulacao e simular_canais (resultado por
  R$ 1.000 investidos, nos 3 cenários). O agente interpreta e ranqueia; os
  números vêm da ferramenta.
- 06 Financeiro: validar_distribuicao, calcular_distribuicao_orcamento e
  projetar_resultados (receita, ROAS e ROI por cenário). O agente define os
  percentuais; valores e KPIs vêm das ferramentas.
- Orquestrador: registrar_briefing, validar_briefing, listar_execucoes e
  validar_execucao (validações cruzadas do fluxo).

## Exemplo oficial
- id_execucao EXEMPLO: Lume Ateliê de Aromas (empresa fictícia de velas,
  incensos e difusores artesanais), objetivo reconhecimento no Instagram.
- O briefing e as saídas dos 6 agentes ficam fixos no servidor e nunca somem.
- Testes com o id EXEMPLO são conferidos, mas não gravados no servidor:
  o exemplo oficial nunca é alterado. A cópia local fica em saidas/.
- Cada grupo desenvolve e testa o seu agente lendo as saídas anteriores do
  EXEMPLO, sem depender de os outros grupos terem rodado.
