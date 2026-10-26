# Servidor MCP — Marketing Campaign Commander

Caixa de ferramentas central do sistema multiagente do trabalho. Fica
hospedado num link único, e todos os agentes dos 3 grupos se conectam nele.
Quando um agente (novo ou antigo) se conecta, ele recebe sozinho a lista de
ferramentas e pode ler as regras do contrato antes de trabalhar.

## O que vai neste repositório (e o que não vai)

- **Vai:** só o servidor, as regras do contrato e as bases fictícias.
- **Não vai:** os agentes. Eles ficam com cada grupo, na pasta do Drive, como
  manda o contrato. Cada agente só precisa do link do servidor (`MCP_URL`).
- **Nunca vai:** a chave do Gemini.

```
mcp-server/
├── servidor_mcp.py        o servidor (14 ferramentas)
├── regras/contrato.md     resumo das regras (ferramenta ler_regras_contrato)
├── dados/                 bases fictícias: concorrentes.json (G1),
│                          premissas_simulacao.json (G2, ainda falta)
├── exemplos/              briefing e saídas de exemplo (id EXEMPLO)
├── testar_servidor.py     testa o servidor sem usar o Gemini
├── requirements.txt
└── render.yaml            configuração do Render
```

## Ferramentas

| Grupo | Ferramenta | Para quê |
|---|---|---|
| Regras | `ler_regras_contrato(secao)` | Regras do contrato, inteiras ou por seção |
| | `ler_ficha_agente(numero)` | Missão, o que lê, para quem entrega, nome da saída |
| | `listar_canais_suportados` | Lista fechada de canais |
| Mesa compartilhada | `registrar_briefing(briefing)` | Orquestrador abre a execução e recebe o id |
| | `ler_briefing(id)` | Briefing da execução (id EXEMPLO = exemplo) |
| | `gravar_saida(id, numero, mensagem)` | Script do agente grava a saída (confere o formato) |
| | `ler_saida_agente(numero, id)` | Lê a saída de outro agente |
| | `listar_execucoes` | Quais execuções e agentes já rodaram |
| | `ler_dados(nome)` | Bases fictícias de `dados/` |
| Validação | `validar_briefing`, `validar_canais`, `verificar_saida` | Conferências do contrato |
| Cálculo | `calcular_distribuicao_orcamento` | % por canal em R$, fechando o orçamento exato |
| | `calcular_indicadores` | ROAS e ROI |

`gravar_saida` e `registrar_briefing` são usadas pelo script, não pelo
Gemini: o modelo nunca grava direto, como pede o contrato.

## Publicar (GitHub + Render, grátis, uns 15 minutos)

### 1. GitHub
1. Crie uma conta em github.com (se ainda não tiver).
2. Clique em **New repository**. Nome: `mcp-server`. Pode ser
   público. Não marque para criar README. Clique em **Create repository**.
3. Na página do repositório vazio, clique em **uploading an existing file**.
4. Arraste **o conteúdo** desta pasta (os arquivos e as pastas `dados`,
   `exemplos`, `regras`), não a pasta em si.
5. Clique em **Commit changes**.

> O arquivo `.gitignore` começa com ponto e pode ficar oculto no
> Windows. Não tem problema se ele não subir.

### 2. Render
1. Entre em render.com e crie a conta com **Sign in with GitHub**.
2. Clique em **New +** → **Blueprint**.
3. Escolha o repositório `mcp-server` e autorize o acesso.
4. O Render lê o `render.yaml` e já preenche tudo (Python, plano Free,
   comando de início). Clique em **Apply** / **Deploy**.
5. Espere o status ficar **Live** (alguns minutos na primeira vez).

Se preferir sem Blueprint: **New +** → **Web Service** → escolha o
repositório → Runtime **Python 3** → Build `pip install -r requirements.txt`
→ Start `python servidor_mcp.py` → Instance **Free**.

### 3. Conferir
1. Abra o link que o Render mostra (algo como
   `https://mcp-campaign-commander.onrender.com`). Deve aparecer
   `"status": "no ar"`.
2. O link para os agentes é esse mesmo com `/mcp` no final:
   `https://mcp-campaign-commander.onrender.com/mcp`
3. No seu PC, teste:
   ```
   pip install -r requirements.txt
   python testar_servidor.py https://mcp-campaign-commander.onrender.com/mcp
   ```

### 4. Atualizar depois
Edite ou suba o arquivo novo no GitHub. O Render publica sozinho a cada
commit. Quando o Grupo 1 ou o Grupo 2 mandarem as bases oficiais, é só
substituir os arquivos em `dados/`.

### 5. (Opcional) Usar seu domínio
No Render: **Settings** → **Custom Domains** → adicione
`mcp.seudominio.com.br`. O Render mostra um registro **CNAME**; crie esse
registro no painel de DNS do Registro.br. O certificado HTTPS é automático.

## Limites do plano grátis

- O servidor **dorme** depois de 15 minutos sem uso e leva cerca de 1 minuto
  para acordar. Os agentes já esperam até 2 minutos. Antes de apresentar,
  abra o link no navegador para acordar.
- Os arquivos da mesa compartilhada (`armazenamento/`) são **apagados**
  quando o servidor dorme, reinicia ou é atualizado. Por isso:
  - cada agente também grava uma cópia local em `saidas/` (registro oficial);
  - o fluxo completo (Orquestrador rodando 01 a 06) deve rodar de uma vez;
  - para testar um agente sozinho, use o id `EXEMPLO`, que lê os exemplos
    fixos do repositório.

## Rodar localmente (sem hospedar)

```
pip install -r requirements.txt
python servidor_mcp.py
```
Link local: `http://localhost:8000/mcp`. Os agentes usam esse link quando
a variável `MCP_URL` não está definida.
