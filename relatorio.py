"""
Relatório final do Marketing Campaign Commander (parte do Orquestrador).

Recebe o briefing e as saídas dos 6 agentes e gera, em saidas/:
- relatorio_final.html : relatório legível para apresentar (abre no navegador,
                         dá para imprimir ou salvar em PDF);
- plano_final.md       : o mesmo conteúdo em Markdown (exigido pelo contrato);
- plano_final.json     : versão estruturada, separando dados do briefing,
                         dados simulados, premissas e resultados calculados.

Nenhum número é calculado aqui: todos vêm das saídas dos agentes, que por sua
vez vieram das ferramentas do servidor MCP. O texto da "leitura executiva" é
opcional e vem do Gemini; se não houver chave, o relatório sai sem ela.
"""

import json
from datetime import datetime
from html import escape

AGENTES = {1: ("Público", "3"), 2: ("Concorrência", "1"), 3: ("Canais", "1"),
           4: ("Criativo", "3"), 5: ("Simulador de Performance", "2"), 6: ("Financeiro", "2")}
CENARIOS = ["pessimista", "realista", "otimista"]
AVISO = "Simulação — não representa resultado real"


def _aviso_dados(conc: dict) -> str:
    """Aviso do topo: diz se os concorrentes vieram da internet ou da base fictícia."""
    reais = [x for x in _lista(conc.get("concorrentes_analisados"))
             if isinstance(x, dict) and x.get("tipo") == "real"]
    if reais:
        return (f"{AVISO}. Os concorrentes marcados como reais foram encontrados na internet "
                "(link da fonte na seção 3); premissas e números de performance são simulados.")
    return f"{AVISO}. Todos os dados, concorrentes e premissas são fictícios."


# ----------------------------------------------------------------- formatos ---

def _num(v, casas=0) -> str:
    try:
        txt = f"{float(v):,.{casas}f}"
    except (TypeError, ValueError):
        return "—"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _reais(v, casas=2) -> str:
    return "—" if v is None else f"R$ {_num(v, casas)}"


def _pct(v) -> str:
    return "—" if v is None else f"{_num(v, 1)}%"


def _dados(saidas: dict, n: int) -> dict:
    s = saidas.get(n) or {}
    return s.get("dados") or {} if s.get("status") == "sucesso" else {}


def _lista(itens) -> list:
    return itens if isinstance(itens, list) else ([] if itens in (None, "") else [itens])


# ------------------------------------------------------- conteúdo (seções) ---

def montar_conteudo(briefing: dict, saidas: dict, meta: dict, leitura: dict | None) -> dict:
    """Junta tudo numa estrutura única, usada pelos três formatos."""
    pub, conc, can = _dados(saidas, 1), _dados(saidas, 2), _dados(saidas, 3)
    cri, sim, fin = _dados(saidas, 4), _dados(saidas, 5), _dados(saidas, 6)

    totais = (fin.get("projecao") or {}).get("totais_por_cenario") or {}
    realista = totais.get("realista") or {}

    premissas = []
    for n in AGENTES:
        s = saidas.get(n) or {}
        for p in _lista(s.get("premissas")):
            premissas.append({"agente": f"{n:02d} {AGENTES[n][0]}", "premissa": str(p)})

    riscos = []
    for c in _lista(conc.get("concorrentes_analisados")):
        if isinstance(c, dict) and str(c.get("ameaca", "")).lower() == "alta":
            riscos.append(f"Concorrente com ameaça alta: {c.get('nome')} — {c.get('justificativa', '')}")
    pess = totais.get("pessimista") or {}
    if pess.get("roi_percentual") is not None and pess["roi_percentual"] < 0:
        riscos.append(f"No cenário pessimista o ROI direto é {_pct(pess['roi_percentual'])}: "
                      "a campanha não se paga em vendas no período.")
    if realista.get("roi_percentual") is not None and realista["roi_percentual"] < 0:
        riscos.append(f"Mesmo no cenário realista o ROI direto é {_pct(realista['roi_percentual'])}. "
                      "Para objetivo de reconhecimento isso é esperado, mas precisa ser explicado ao cliente.")
    if meta.get("substitutos"):
        nomes = ", ".join(f"{n:02d} {AGENTES[n][0]}" for n in meta["substitutos"])
        riscos.append(f"Agentes ainda não entregues pelos grupos ({nomes}): nesta execução foram usadas "
                      "as saídas do exemplo oficial no lugar deles.")
    riscos.append("As premissas de simulação (CPM, CTR, conversão) são fictícias e ainda podem mudar "
                  "após a revisão do Grupo 2.")
    if leitura:
        riscos = _lista(leitura.get("riscos")) + riscos

    canais = [c for c in _lista(can.get("canais_escolhidos")) if isinstance(c, dict)]
    resumo_auto = (
        f"Campanha de {briefing.get('objetivo_campanha', '')} para a {briefing.get('empresa', '')} "
        f"({briefing.get('produto_ou_servico', '')}), com {_reais(briefing.get('orcamento_total'), 0)} "
        f"em {briefing.get('duracao_dias', '')} dias, em {len(canais)} canais: "
        f"{', '.join(c.get('canal', '') for c in sorted(canais, key=lambda c: c.get('prioridade', 99)))}."
    )
    if realista:
        resumo_auto += (f" No cenário realista, a projeção é de {_num(realista.get('alcance'))} pessoas "
                        f"alcançadas, {_num(realista.get('novos_seguidores'))} novos seguidores e "
                        f"{_num(realista.get('conversoes'))} vendas.")

    return {
        "meta": meta, "briefing": briefing, "leitura": leitura, "resumo_auto": resumo_auto,
        "publico": pub, "concorrencia": conc, "canais": can, "criativo": cri,
        "simulador": sim, "financeiro": fin, "totais": totais,
        "premissas": premissas, "riscos": riscos,
        "rastreio": [{"numero": n, "agente": AGENTES[n][0], "grupo": AGENTES[n][1],
                      "status": (saidas.get(n) or {}).get("status", "pendente"),
                      "data_hora": (saidas.get(n) or {}).get("data_hora", ""),
                      "substituto": n in meta.get("substitutos", [])} for n in AGENTES],
    }


# ---------------------------------------------------------------- HTML ---

_CSS = """
:root{--bg:#f4f5f7;--card:#fff;--txt:#1b2230;--sub:#5b6474;--borda:#e2e5eb;--acento:#7a4b2a;
--acento2:#f3e9e1;--ok:#1f8a4c;--okbg:#e5f5ec;--alerta:#9a6200;--alertabg:#fdf3dc;--barra:#b9835a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:28px 16px 56px}
header{background:var(--acento);color:#fff;border-radius:14px;padding:26px 28px;margin-bottom:18px}
header h1{margin:0 0 6px;font-size:26px;line-height:1.2}header p{margin:0;opacity:.9}
.faixa{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.faixa span{background:rgba(255,255,255,.16);border-radius:999px;padding:3px 12px;font-size:13px}
section{background:var(--card);border:1px solid var(--borda);border-radius:12px;padding:20px 22px;margin:14px 0}
h2{font-size:18px;margin:0 0 12px;color:var(--acento)}h3{font-size:15px;margin:16px 0 6px}
.num{font-variant-numeric:tabular-nums}.sub{color:var(--sub)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 6px;
border-bottom:1px solid var(--borda);vertical-align:top}th{color:var(--sub);font-weight:600;font-size:13px}
td.r,th.r{text-align:right}.tabela{overflow-x:auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:6px 0 4px}
.kpi{background:var(--acento2);border-radius:10px;padding:12px 14px}
.kpi b{display:block;font-size:22px;line-height:1.2}.kpi span{color:var(--sub);font-size:13px}
.tag{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600}
.alta{color:#b42318;background:#fde8e7}.media{color:var(--alerta);background:var(--alertabg)}
.baixa{color:var(--ok);background:var(--okbg)}.sub-tag{color:var(--alerta);background:var(--alertabg)}
.ok{color:var(--ok);background:var(--okbg)}
.msg{border:1px solid var(--borda);border-radius:10px;padding:12px 14px;margin:10px 0}
.msg .canal{font-weight:700}.msg .cta{margin-top:6px;font-weight:600;color:var(--acento)}
.barra{height:10px;background:var(--barra);border-radius:6px}
ul{margin:6px 0 0;padding-left:20px}li{margin:3px 0}
.aviso{background:var(--alertabg);color:var(--alerta);border-radius:10px;padding:10px 14px;font-weight:600}
footer{color:var(--sub);font-size:13px;margin-top:20px}
@media print{body{background:#fff}main{padding:0}section,header{break-inside:avoid}
header{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def _li(itens) -> str:
    itens = [i for i in _lista(itens) if i]
    return "<ul>" + "".join(f"<li>{escape(str(i))}</li>" for i in itens) + "</ul>" if itens else \
        "<p class='sub'>—</p>"


def _sem_dados(nome: str) -> str:
    return f"<p class='sub'>Sem dados do agente {escape(nome)} nesta execução.</p>"


def gerar_html(c: dict) -> str:
    b, m = c["briefing"], c["meta"]
    partes = []

    partes.append(
        f"<header><p>Plano de campanha · Marketing Campaign Commander</p>"
        f"<h1>{escape(str(b.get('empresa', '')))}</h1>"
        f"<p>{escape(str(b.get('produto_ou_servico', '')))}</p><div class='faixa'>"
        f"<span>Objetivo: {escape(str(b.get('objetivo_campanha', '')))}</span>"
        f"<span>Orçamento: {_reais(b.get('orcamento_total'), 0)}</span>"
        f"<span>{escape(str(b.get('duracao_dias', '')))} dias</span>"
        f"<span>{escape(str(b.get('regiao', '')))}</span></div></header>"
        f"<p class='aviso'>{escape(_aviso_dados(c['concorrencia']))}</p>")
    if m.get("parcial"):
        n = m["parcial"]
        partes.append(f"<p class='aviso' style='color:#b42318;background:#fde8e7'>RELATÓRIO PARCIAL: o fluxo "
                      f"parou no agente {n:02d} ({escape(AGENTES[n][0])}), que terminou com erro. As seções "
                      "seguintes ficaram sem dados.</p>")

    # 1. Resumo
    leitura = c.get("leitura") or {}
    resumo = leitura.get("resumo_executivo") or c["resumo_auto"]
    t = c["totais"].get("realista") or {}
    kpis = ""
    if t:
        kpis = "<div class='kpis'>" + "".join(
            f"<div class='kpi'><b class='num'>{v}</b><span>{r}</span></div>" for v, r in [
                (_num(t.get("alcance")), "pessoas alcançadas"),
                (_num(t.get("novos_seguidores")), "novos seguidores"),
                (_num(t.get("conversoes")), "vendas projetadas"),
                (_reais(t.get("receita"), 0), "receita projetada"),
            ]) + "</div><p class='sub'>Cenário realista.</p>"
    rec = _li(leitura.get("recomendacoes")) if leitura.get("recomendacoes") else ""
    partes.append(f"<section><h2>1. Resumo da campanha</h2><p>{escape(resumo)}</p>{kpis}"
                  + (f"<h3>Recomendações</h3>{rec}" if rec else "")
                  + ("<p class='sub'>Leitura executiva escrita pelo Gemini a partir das saídas dos agentes; "
                     "os números vêm das ferramentas.</p>" if leitura else "") + "</section>")

    # 2. Público
    p = c["publico"]
    pp = p.get("publico_prioritario") or {}
    if pp:
        sec = "".join(f"<li><b>{escape(str(s.get('nome', '')))}</b>: {escape(str(s.get('descricao', '')))}"
                      f"{' — ' + escape(str(s.get('por_que_importa'))) if s.get('por_que_importa') else ''}</li>"
                      for s in _lista(p.get("publicos_secundarios")) if isinstance(s, dict))
        partes.append(
            f"<section><h2>2. Público prioritário</h2><h3>{escape(str(pp.get('nome', '')))}</h3>"
            f"<p>{escape(str(pp.get('descricao', '')))}</p>"
            f"<p class='sub'>{escape(str(pp.get('faixa_etaria', '')))} · {escape(str(pp.get('genero_predominante', '')))}"
            f" · {escape(str(pp.get('regiao', '')))}</p>"
            f"<h3>Dores</h3>{_li(pp.get('dores'))}<h3>Motivações</h3>{_li(pp.get('motivacoes'))}"
            f"<h3>Comportamento digital</h3><p>{escape(str(pp.get('comportamento_digital', '')))}</p>"
            + (f"<h3>Públicos secundários</h3><ul>{sec}</ul>" if sec else "")
            + f"<h3>Insights</h3>{_li(p.get('insights'))}</section>")
    else:
        partes.append(f"<section><h2>2. Público prioritário</h2>{_sem_dados('01')}</section>")

    # 3. Concorrência
    def _origem_html(x: dict) -> str:
        fonte = str(x.get("fonte") or "")
        if x.get("tipo") == "real" and fonte.startswith("http"):
            return (f"<span class='sub' style='font-size:12px'>real · "
                    f"<a href='{escape(fonte)}' target='_blank' rel='noopener'>fonte</a></span>")
        return "<span class='sub' style='font-size:12px'>fictício</span>"

    co = c["concorrencia"]
    if co:
        linhas = "".join(
            f"<tr><td><b>{escape(str(x.get('nome', '')))}</b><br>{_origem_html(x)}</td>"
            f"<td>{escape(str(x.get('posicionamento', '')))}</td>"
            f"<td><span class='tag {escape(str(x.get('ameaca', '')).lower())}'>{escape(str(x.get('ameaca', '')))}</span></td>"
            f"<td>{escape(str(x.get('justificativa', '')))}</td></tr>"
            for x in _lista(co.get("concorrentes_analisados")) if isinstance(x, dict))
        partes.append(
            "<section><h2>3. Concorrência e diferenciais</h2><div class='tabela'><table><tr><th>Concorrente</th>"
            "<th>Posicionamento</th><th>Ameaça</th><th>Por quê</th></tr>" + linhas + "</table></div>"
            f"<h3>Lacunas de mercado</h3>{_li(co.get('lacunas_de_mercado'))}"
            f"<h3>Diferenciais sugeridos</h3>{_li(co.get('diferenciais_sugeridos'))}"
            f"<p class='sub'>Canais mais disputados: {escape(', '.join(_lista(co.get('canais_mais_disputados'))))}.</p>"
            "</section>")
    else:
        partes.append(f"<section><h2>3. Concorrência e diferenciais</h2>{_sem_dados('02')}</section>")

    # 4. Criativo
    cr = c["criativo"]
    if cr:
        cc = cr.get("conceito_criativo") or {}
        msgs = "".join(
            f"<div class='msg'><div class='canal'>{escape(str(x.get('canal', '')))} "
            f"<span class='sub'>· {escape(str(x.get('formato', '')))}</span></div>"
            f"<div><b>{escape(str(x.get('titulo', '')))}</b></div><div>{escape(str(x.get('texto', '')))}</div>"
            f"<div class='cta'>→ {escape(str(x.get('chamada_para_acao', '')))}</div></div>"
            for x in _lista(cr.get("mensagens_por_canal")) if isinstance(x, dict))
        partes.append(
            f"<section><h2>4. Conceito criativo e mensagens por canal</h2>"
            f"<h3>“{escape(str(cc.get('nome', '')))}”</h3><p>{escape(str(cc.get('ideia_central', '')))}</p>"
            f"<p class='sub'>Tom de voz: {escape(str(cc.get('tom_de_voz', '')))}</p>{msgs}</section>")
    else:
        partes.append(f"<section><h2>4. Conceito criativo e mensagens por canal</h2>{_sem_dados('04')}</section>")

    # 5. Canais
    ca = c["canais"]
    if ca:
        esc = sorted([x for x in _lista(ca.get("canais_escolhidos")) if isinstance(x, dict)],
                     key=lambda x: x.get("prioridade", 99))
        linhas = "".join(f"<tr><td class='num'>{escape(str(x.get('prioridade', '')))}</td>"
                         f"<td><b>{escape(str(x.get('canal', '')))}</b></td><td>{escape(str(x.get('papel', '')))}</td>"
                         f"<td>{escape(str(x.get('justificativa', '')))}</td></tr>" for x in esc)
        desc = "".join(f"<li><b>{escape(str(x.get('canal', '')))}</b>: {escape(str(x.get('motivo', '')))}</li>"
                       for x in _lista(ca.get("canais_descartados")) if isinstance(x, dict))
        partes.append("<section><h2>5. Canais escolhidos</h2><div class='tabela'><table><tr><th>#</th><th>Canal</th>"
                      "<th>Papel</th><th>Justificativa</th></tr>" + linhas + "</table></div>"
                      + (f"<h3>Canais descartados</h3><ul>{desc}</ul>" if desc else "") + "</section>")
    else:
        partes.append(f"<section><h2>5. Canais escolhidos</h2>{_sem_dados('03')}</section>")

    # 6. Distribuição
    fi = c["financeiro"]
    dist = [d for d in _lista(fi.get("distribuicao")) if isinstance(d, dict)]
    if dist:
        maior = max(float(d.get("percentual", 0)) for d in dist) or 1
        linhas = "".join(
            f"<tr><td><b>{escape(str(d.get('canal', '')))}</b></td><td class='r num'>{_pct(d.get('percentual'))}</td>"
            f"<td class='r num'>{_reais(d.get('valor'))}</td><td style='width:40%'>"
            f"<div class='barra' style='width:{float(d.get('percentual', 0)) / maior * 100:.0f}%'></div></td></tr>"
            for d in sorted(dist, key=lambda d: -float(d.get("valor", 0))))
        partes.append("<section><h2>6. Distribuição do orçamento</h2><div class='tabela'><table><tr><th>Canal</th>"
                      "<th class='r'>%</th><th class='r'>Valor</th><th></th></tr>" + linhas
                      + f"<tr><td><b>Total</b></td><td></td><td class='r num'><b>{_reais(fi.get('total_distribuido'))}</b>"
                      "</td><td></td></tr></table></div>"
                      f"<h3>Justificativa</h3>{_li(fi.get('justificativa'))}</section>")
    else:
        partes.append(f"<section><h2>6. Distribuição do orçamento</h2>{_sem_dados('06')}</section>")

    # 7 e 8. KPIs e financeiro
    tot = c["totais"]
    if tot:
        def linha(rotulo, chave, fmt):
            return (f"<tr><td>{rotulo}</td>" + "".join(
                f"<td class='r num'>{fmt((tot.get(cen) or {}).get(chave))}</td>" for cen in CENARIOS) + "</tr>")
        cab = "<tr><th>Indicador</th>" + "".join(f"<th class='r'>{cen.capitalize()}</th>" for cen in CENARIOS) + "</tr>"
        kp = "".join(linha(r, k, f) for r, k, f in [
            ("Impressões", "impressoes", _num), ("Alcance (pessoas)", "alcance", _num),
            ("Cliques", "cliques", _num), ("Engajamentos", "engajamentos", _num),
            ("Novos seguidores", "novos_seguidores", _num), ("Custo por seguidor", "custo_por_seguidor", _reais),
            ("Vendas (conversões)", "conversoes", _num)])
        fn = "".join(linha(r, k, f) for r, k, f in [
            ("Investimento", "investimento", _reais), ("Receita", "receita", _reais),
            ("ROAS", "roas", lambda v: "—" if v is None else _num(v, 2) + "x"),
            ("ROI", "roi_percentual", _pct)])
        partes.append(f"<section><h2>7. KPIs projetados</h2><div class='tabela'><table>{cab}{kp}</table></div></section>"
                      f"<section><h2>8. Indicadores financeiros</h2><div class='tabela'><table>{cab}{fn}</table></div>"
                      "<p class='sub'>Receita não é lucro, e ROAS não é ROI. ROAS = receita ÷ investimento. "
                      "ROI = (receita × margem − investimento) ÷ investimento"
                      + ("" if b.get("margem_contribuicao_percentual") is not None else
                         ". Sem margem no briefing, o ROI não é calculado") + ".</p></section>")
    else:
        partes.append(f"<section><h2>7. KPIs projetados</h2>{_sem_dados('06')}</section>")

    # Simulador (eficiência por canal)
    si = c["simulador"]
    rk = [r for r in _lista(si.get("ranking_eficiencia")) if isinstance(r, dict)]
    if rk:
        res = si.get("resultados_por_canal") or {}
        linhas = "".join(
            f"<tr><td class='num'>{escape(str(r.get('posicao', '')))}</td><td><b>{escape(str(r.get('canal', '')))}</b></td>"
            f"<td class='r num'>{_num(((res.get(r.get('canal')) or {}).get('realista') or {}).get('novos_seguidores'))}</td>"
            f"<td class='r num'>{_num(((res.get(r.get('canal')) or {}).get('realista') or {}).get('conversoes'), 1)}</td>"
            f"<td>{escape(str(r.get('motivo', '')))}</td></tr>" for r in rk)
        partes.append("<section><h2>Eficiência por canal (a cada R$ 1.000)</h2><div class='tabela'><table><tr><th>#</th>"
                      "<th>Canal</th><th class='r'>Seguidores</th><th class='r'>Vendas</th><th>Motivo</th></tr>"
                      + linhas + f"</table></div>{_li(si.get('leitura'))}</section>")

    # 9. Riscos
    partes.append(f"<section><h2>9. Riscos</h2>{_li(c['riscos'])}</section>")

    # 10. Premissas
    prem = "".join(f"<tr><td>{escape(p['agente'])}</td><td>{escape(p['premissa'])}</td></tr>" for p in c["premissas"])
    partes.append("<section><h2>10. Premissas e limitações</h2>"
                  f"<p class='aviso'>{AVISO}.</p><div class='tabela'><table><tr><th>Agente</th><th>Premissa</th></tr>"
                  + prem + "</table></div></section>")

    # Rastreabilidade
    selo_sub = " <span class='tag sub-tag'>substituto</span>"
    rs = "".join(
        f"<tr><td class='num'>{r['numero']:02d}</td><td>{escape(r['agente'])}</td><td>Grupo {r['grupo']}</td>"
        f"<td><span class='tag {'ok' if r['status'] == 'sucesso' else 'media'}'>{escape(r['status'])}</span>"
        f"{selo_sub if r['substituto'] else ''}</td>"
        f"<td class='num'>{escape(str(r['data_hora']).replace('T', ' '))}</td></tr>" for r in c["rastreio"])
    partes.append("<section><h2>Rastreabilidade da execução</h2><div class='tabela'><table><tr><th>Nº</th><th>Agente"
                  "</th><th>Grupo</th><th>Status</th><th>Gravado em</th></tr>" + rs + "</table></div>"
                  f"<p class='sub'>Execução {escape(m.get('id_execucao', ''))} · validação cruzada: "
                  f"{escape(m.get('validacao', ''))}</p></section>")

    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Plano de campanha — {escape(str(b.get('empresa', '')))}</title><style>{_CSS}</style></head>"
            f"<body><main>{''.join(partes)}<footer>Gerado em {escape(m.get('gerado_em', ''))} pelo Orquestrador do "
            f"Marketing Campaign Commander.</footer></main></body></html>")


# ----------------------------------------------------------------- Markdown ---

def gerar_markdown(c: dict) -> str:
    b, m, t = c["briefing"], c["meta"], c["totais"]
    leitura = c.get("leitura") or {}
    L = [f"# Plano de campanha — {b.get('empresa', '')}", "",
         f"> {_aviso_dados(c['concorrencia'])}", ""]
    if m.get("parcial"):
        L += [f"> **RELATÓRIO PARCIAL:** o fluxo parou no agente {m['parcial']:02d} "
              f"({AGENTES[m['parcial']][0]}).", ""]
    L += [
         f"Execução `{m.get('id_execucao', '')}` · gerado em {m.get('gerado_em', '')}", "",
         "## 1. Resumo da campanha", "", leitura.get("resumo_executivo") or c["resumo_auto"], ""]
    pp = (c["publico"].get("publico_prioritario") or {})
    L += ["## 2. Público prioritário", "", f"**{pp.get('nome', '—')}** — {pp.get('descricao', '')}", ""]
    L += [f"- Dor: {d}" for d in _lista(pp.get("dores"))] + [""]
    L += ["## 3. Concorrência e diferenciais", ""]
    L += [f"- **{x.get('nome')}** (ameaça {x.get('ameaca')}; "
          + (f"real, fonte: {x.get('fonte')}" if x.get("tipo") == "real" else "fictício")
          + f"): {x.get('justificativa', '')}"
          for x in _lista(c["concorrencia"].get("concorrentes_analisados")) if isinstance(x, dict)]
    L += [""] + [f"- Diferencial: {d}" for d in _lista(c["concorrencia"].get("diferenciais_sugeridos"))] + [""]
    cc = c["criativo"].get("conceito_criativo") or {}
    L += ["## 4. Conceito criativo e mensagens por canal", "", f"**{cc.get('nome', '—')}** — {cc.get('ideia_central', '')}", ""]
    L += [f"- **{x.get('canal')}**: {x.get('titulo', '')} — {x.get('texto', '')} → {x.get('chamada_para_acao', '')}"
          for x in _lista(c["criativo"].get("mensagens_por_canal")) if isinstance(x, dict)] + [""]
    L += ["## 5. Canais escolhidos", ""]
    L += [f"{x.get('prioridade')}. **{x.get('canal')}** — {x.get('papel', '')}: {x.get('justificativa', '')}"
          for x in sorted([x for x in _lista(c["canais"].get("canais_escolhidos")) if isinstance(x, dict)],
                          key=lambda x: x.get("prioridade", 99))] + [""]
    L += ["## 6. Distribuição do orçamento", "", "| Canal | % | Valor |", "|---|---:|---:|"]
    L += [f"| {d.get('canal')} | {_pct(d.get('percentual'))} | {_reais(d.get('valor'))} |"
          for d in _lista(c["financeiro"].get("distribuicao")) if isinstance(d, dict)]
    L += [f"| **Total** | | **{_reais(c['financeiro'].get('total_distribuido'))}** |", ""]
    if t:
        L += ["## 7. KPIs projetados e 8. Indicadores financeiros", "",
              "| Indicador | Pessimista | Realista | Otimista |", "|---|---:|---:|---:|"]
        for r, k, f in [("Alcance", "alcance", _num), ("Novos seguidores", "novos_seguidores", _num),
                        ("Vendas", "conversoes", _num), ("Receita", "receita", _reais),
                        ("ROAS", "roas", lambda v: "—" if v is None else _num(v, 2) + "x"),
                        ("ROI", "roi_percentual", _pct)]:
            L.append(f"| {r} | " + " | ".join(f((t.get(cen) or {}).get(k)) for cen in CENARIOS) + " |")
        L += ["", "Receita não é lucro, e ROAS não é ROI.", ""]
    L += ["## 9. Riscos", ""] + [f"- {r}" for r in c["riscos"]] + [""]
    L += ["## 10. Premissas e limitações", "", f"> {AVISO}.", ""]
    L += [f"- ({p['agente']}) {p['premissa']}" for p in c["premissas"]] + [""]
    return "\n".join(L)


# --------------------------------------------------------------------- JSON ---

def gerar_json(c: dict) -> dict:
    return {
        "aviso": AVISO,
        "id_execucao": c["meta"].get("id_execucao"),
        "gerado_em": c["meta"].get("gerado_em"),
        "dados_do_briefing": c["briefing"],
        "dados_simulados": {
            "publico": c["publico"], "concorrencia": c["concorrencia"], "canais": c["canais"],
            "criativo": c["criativo"], "simulacao_por_canal": c["simulador"],
        },
        "premissas": c["premissas"],
        "resultados_calculados": {
            "distribuicao": c["financeiro"].get("distribuicao"),
            "total_distribuido": c["financeiro"].get("total_distribuido"),
            "kpis_por_cenario": c["totais"],
        },
        "riscos": c["riscos"],
        "leitura_executiva": c.get("leitura"),
        "rastreabilidade": c["rastreio"],
        "validacao_cruzada": c["meta"].get("validacao"),
    }


def salvar(pasta, briefing, saidas, meta, leitura=None) -> dict:
    """Gera os três arquivos em 'pasta' e devolve os caminhos."""
    meta = dict(meta)
    meta.setdefault("gerado_em", datetime.now().strftime("%d/%m/%Y %H:%M"))
    c = montar_conteudo(briefing, saidas, meta, leitura)
    pasta.mkdir(exist_ok=True)
    arquivos = {
        "html": pasta / "relatorio_final.html",
        "md": pasta / "plano_final.md",
        "json": pasta / "plano_final.json",
    }
    arquivos["html"].write_text(gerar_html(c), encoding="utf-8")
    arquivos["md"].write_text(gerar_markdown(c), encoding="utf-8")
    arquivos["json"].write_text(json.dumps(gerar_json(c), ensure_ascii=False, indent=2), encoding="utf-8")
    return arquivos
