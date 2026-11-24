// Proposições e Temas: área por tema/semana, acurácia da IA, treemap, tramitação, setores e tabela.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, corGradiente, corTema, gauge, montar } from '../charts.js';
import { abrirDrawer, badgeImpacto, chipTema, Tabela, vazio } from '../ui.js';
import * as estado from '../state.js';
import * as fmt from '../format.js';

const m = await iniciar();
const nomesTemas = m.temas.map((t) => t.nome);
let filtro = estado.ler();
const passa = (tema) => !filtro.temas.length || filtro.temas.includes(tema);

// ------------------------------------------------------------------ filtro de temas (chips)
const caixa = document.getElementById('filtro-temas');
function desenharFiltro() {
  caixa.innerHTML = nomesTemas.map((t) => `<button type="button" class="btn" aria-pressed="${filtro.temas.includes(t)}" data-tema="${fmt.escapar(t)}">
    <span class="chip__dot" style="background:${corTema(t)}"></span>${fmt.escapar(t)}</button>`).join('');
  caixa.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    const t = b.dataset.tema;
    const temas = filtro.temas.includes(t) ? filtro.temas.filter((x) => x !== t) : [...filtro.temas, t];
    filtro = estado.gravar({ temas });
  }));
}
document.getElementById('limpar-temas').addEventListener('click', () => { filtro = estado.gravar({ temas: [] }); });
desenharFiltro();

const ts = await dados('proposicoes_tema_semana');
const props = await dados('proposicoes_recentes');
const graficos = {};

function desenharArea() {
  const semanas = [...new Set(ts.map((d) => d.inicio_semana))].sort();
  const temas = nomesTemas.filter((t) => passa(t) && ts.some((d) => d.tema === t));
  const el = document.getElementById('graf-area');
  el.classList.remove('skeleton');
  graficos.area?.instancia.dispose();
  if (!temas.length) { el.innerHTML = vazio(); return; }
  const serie = (t) => semanas.map((s) => ts.filter((d) => d.tema === t && d.inicio_semana === s).reduce((a, d) => a + d.qtd, 0));
  // degradê pelo total do período: tema com mais proposições em verde, com menos em vermelho (como no
  // treemap); a pilha vai do maior (base) ao menor (topo) e um filete separa as faixas de cor parecida
  const series = temas.map((t) => ({ t, data: serie(t) })).map((x) => ({ ...x, total: x.data.reduce((a, v) => a + v, 0) }))
    .sort((a, b) => b.total - a.total);
  const [min, max] = [Math.min(...series.map((x) => x.total)), Math.max(...series.map((x) => x.total))];
  graficos.area = montar(el, (tm) => ({
    grid: { left: 8, right: 16, top: 64, bottom: 8, containLabel: true }, tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0, left: 0 },
    xAxis: { type: 'category', data: semanas, boundaryGap: false, axisLabel: { formatter: fmt.dataCurta } },
    yAxis: { type: 'value', axisLabel: { formatter: fmt.num } },
    series: series.map((x) => ({
      name: x.t, type: 'line', stack: 'total', areaStyle: { opacity: 0.9 }, showSymbol: false,
      lineStyle: { width: 0.6, color: tm.surface }, color: corGradiente(x.total, min, max, true), data: x.data,
    })),
  }));
}

// nome do tipo de proposição por extenso: "PL" sozinho se confunde com o partido
const TIPOS = {
  PL: 'Projeto de Lei', PDL: 'Projeto de Decreto Legislativo', PLP: 'Projeto de Lei Complementar',
  MPV: 'Medida Provisória', PEC: 'Proposta de Emenda à Constituição', PRC: 'Projeto de Resolução',
  PLN: 'Projeto de Lei do Congresso', PLV: 'Projeto de Lei de Conversão', REQ: 'Requerimento', INC: 'Indicação',
};
const nomeTipo = (sigla) => (TIPOS[sigla] ? `${TIPOS[sigla]} (${sigla})` : sigla);

function desenharTreemap() {
  const el = document.getElementById('graf-treemap');
  el.classList.remove('skeleton');
  graficos.treemap?.instancia.dispose();
  const arvore = {};
  for (const d of ts) if (passa(d.tema)) { arvore[d.tema] ??= {}; arvore[d.tema][d.sigla_tipo] = (arvore[d.tema][d.sigla_tipo] || 0) + d.qtd; }
  // tema com mais proposições em verde, com menos em vermelho (mesma regra dos setores)
  const somas = Object.values(arvore).map((tipos) => Object.values(tipos).reduce((a, b) => a + b, 0));
  const [min, max] = [Math.min(...somas), Math.max(...somas)];
  const data = Object.entries(arvore).map(([tema, tipos], i) => ({
    name: tema, itemStyle: { color: corGradiente(somas[i], min, max, true) },
    children: Object.entries(tipos).map(([tipo, v]) => ({ name: tipo, value: v })),
  }));
  if (!data.length) { el.innerHTML = vazio(); return; }
  graficos.treemap = montar(el, (t) => ({
    tooltip: { formatter: (p) => `${fmt.escapar(p.treePathInfo.map((x, i) => (i === 2 ? nomeTipo(x.name) : x.name)).filter(Boolean).join(' › '))}: <b>${fmt.num(p.value)}</b>` },
    series: [{
      type: 'treemap', roam: false, nodeClick: false, breadcrumb: { show: false }, width: '100%', height: '100%',
      // retângulo grande: nome por extenso; médio: "Projeto de Lei"; pequeno: só a sigla (o tooltip mostra tudo)
      label: { show: true, fontSize: 11, overflow: 'truncate', ellipsis: '…',
        formatter: (p) => (TIPOS[p.name] ? `${TIPOS[p.name]}\n${p.name}` : p.name) }, upperLabel: { show: true, height: 22, color: '#fff', fontWeight: 600 },
      itemStyle: { borderColor: t.surface, borderWidth: 2, gapWidth: 2 },
      // os tipos herdam a cor do tema; a faixa do título usa um tom mais escuro dela
      levels: [
        { itemStyle: { borderWidth: 0, gapWidth: 3 } },
        { itemStyle: { gapWidth: 1, borderColorSaturation: 0.6 } },
      ],
      data,
    }],
  }));
}

function desenharTabela() {
  if (graficos.tabela) { graficos.tabela.atualizar(); return; }
  graficos.tabela = new Tabela(document.getElementById('tabela-proposicoes'), {
    linhas: props, nomeCsv: 'proposicoes_recentes', filtroExtra: (p) => passa(p.tema_ia),
    colunas: [
      { chave: 'rotulo', titulo: 'Proposição', valor: (p) => fmt.proposicao(p), render: (p) => `<strong>${fmt.escapar(fmt.proposicao(p))}</strong>` },
      { chave: 'data_apresentacao', titulo: 'Apresentação', render: (p) => fmt.data(p.data_apresentacao) },
      { chave: 'tema_ia', titulo: 'Tema (IA)', render: (p) => chipTema(p.tema_ia) },
      { chave: 'nivel_impacto', titulo: 'Impacto', render: (p) => badgeImpacto(p.nivel_impacto) },
      { chave: 'resumo_executivo', titulo: 'Resumo da IA', clip: true, valor: (p) => p.resumo_executivo || p.ementa },
      { chave: 'relevancia_score', titulo: 'Relevância', num: true, render: (p) => fmt.num1((p.relevancia_score || 0) * 100) },
    ],
    aoClicar: detalhe,
  });
}

async function detalhe(p) {
  const corpo = abrirDrawer(`<p class="muted">${fmt.escapar(p.sigla_tipo)} · apresentada em ${fmt.data(p.data_apresentacao)}</p>
    <h2>${fmt.escapar(fmt.proposicao(p))}</h2>
    <div class="item__head">${chipTema(p.tema_ia)}${badgeImpacto(p.nivel_impacto)}${p.em_pauta ? '<span class="badge badge--medio">em pauta</span>' : ''}</div>
    <h3>Resumo executivo (IA)</h3><p>${fmt.escapar(p.resumo_executivo || '—')}</p>
    <h3>Ementa</h3><p>${fmt.escapar(p.ementa)}</p>
    <h3>Setores afetados</h3><p>${(p.setores_afetados || []).map((s) => `<span class="chip">${fmt.escapar(s)}</span>`).join(' ') || '—'}</p>
    <h3>Classificação</h3>
    <dl class="kv">
      <dt>Tema da IA</dt><dd>${fmt.escapar(p.tema_ia)} (similaridade ${fmt.num1((p.tema_ia_score || 0) * 100)}%)</dd>
      <dt>Segundo tema</dt><dd>${fmt.escapar(p.tema_ia_segundo || '—')}</dd>
      <dt>Temas oficiais</dt><dd>${fmt.escapar((p.temas_oficiais || []).join(', ') || '—')}</dd>
      <dt>Situação</dt><dd>${fmt.escapar(p.situacao || '—')}</dd>
      <dt>Órgão</dt><dd>${fmt.escapar(p.orgao || '—')}</dd>
      <dt>Regime</dt><dd>${fmt.escapar(p.regime || '—')}</dd>
      <dt>Relevância</dt><dd>${fmt.num1((p.relevancia_score || 0) * 100)} / 100</dd>
    </dl>
    <p><a href="${fmt.escapar(p.link_camara)}" target="_blank" rel="noopener">Abrir na Câmara dos Deputados<span class="sr-only"> (abre em nova aba)</span></a></p>
    <h3>Proposições parecidas (busca semântica)</h3><div id="similares" class="stack"><div class="skeleton" style="height:120px"></div></div>`, fmt.proposicao(p));
  const sim = (await dados('similares'))[String(p.id_proposicao)] || [];
  corpo.querySelector('#similares').innerHTML = sim.length ? sim.map((s) => `<div class="item"><div class="item__head"><span class="item__title">${fmt.escapar(s.rotulo)}</span>
    <span class="muted">${fmt.num1(s.similaridade * 100)}% parecida</span></div><p class="item__text">${fmt.escapar(s.ementa)}</p></div>`).join('') : vazio('Sem vizinhas calculadas.');
}

await seguro(document.getElementById('graf-area'), desenharArea);
await seguro(document.getElementById('graf-treemap'), desenharTreemap);
await seguro(document.getElementById('tabela-proposicoes'), desenharTabela);

await seguro(document.getElementById('graf-gauge'), async () => {
  const el = document.getElementById('graf-gauge');
  el.classList.remove('skeleton');
  const ia = m.ia || {};
  montar(el, gauge({ valor: Math.round((ia.acuracia_sem_vazamento || 0) * 1000) / 10, rotulo: 'sem vazamento', gradiente: true }));
  document.getElementById('kv-ia').innerHTML = `
    <dt>Base inteira</dt><dd>${fmt.pctFrac(ia.acuracia)} de ${fmt.num(ia.avaliadas)} proposições</dd>
    <dt>Classificadas</dt><dd>${fmt.pctFrac(ia.cobertura)} (limiar ${fmt.num1((ia.limiar || 0) * 100)}%)</dd>
    <dt>Custo de IA</dt><dd>US$ ${fmt.num1(ia.custo_total_usd)} no total</dd>`;
});

// Os gráficos abaixo também respeitam o filtro de temas (botões no topo da página)
const [tramitacao, setores, projetosPartido, partidos] = await Promise.all(
  [dados('tramitacao_tema'), dados('setores'), dados('projetos_partido'), dados('partidos')]);
const vazioEm = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); el.innerHTML = vazio(); };

// Tempo de tramitação: comparação entre temas, então não some com nenhum — com filtro ativo, os temas
// escolhidos ficam em destaque e os demais esmaecidos (o tempo de um tema sozinho não diz se é lento)
function desenharTramitacao() {
  // ordenado pela mediana: tramitação mais lenta em vermelho, mais rápida em verde
  const tr = tramitacao.filter((d) => d.tema !== 'Outros')
    .sort((a, b) => (b.mediana_dias ?? -1) - (a.mediana_dias ?? -1));
  const el = document.getElementById('graf-tramitacao');
  el.classList.remove('skeleton');
  const opac = (d) => (passa(d.tema) ? 1 : 0.2);
  montar(el, barras({
    categorias: tr.map((d) => d.tema), horizontal: true, formatter: (v) => `${fmt.num(v)} dias`, gradiente: true,
    series: [
      { name: 'Mediana', data: tr.map((d) => ({ value: d.mediana_dias, itemStyle: { opacity: opac(d) } })) },
      { name: 'Percentil 90', data: tr.map((d) => ({ value: d.p90_dias, itemStyle: { opacity: opac(d) } })), itemStyle: { color: 'rgba(148,163,184,.55)' } },
    ],
  }), { tabela: { colunas: ['Tema', 'Proposições', 'Mediana (dias)', 'P90 (dias)'], linhas: tr.map((d) => [d.tema, d.qtd, d.mediana_dias, d.p90_dias]) } });
}

// Projetos por partido (autor principal): total ou por deputado, somados só nos temas filtrados; o
// tooltip mostra o maior autor, porque um só deputado pode responder por boa parte do partido
let modoProjetos = 'total';
function desenharProjetos() {
  const porDep = modoProjetos === 'por-deputado';
  const deputados = Object.fromEntries(partidos.map((p) => [p.sigla_partido, p.deputados]));
  const agg = {};
  for (const d of projetosPartido) {
    if (!passa(d.tema) || !deputados[d.sigla_partido]) continue;
    const a = (agg[d.sigla_partido] ??= { sigla: d.sigla_partido, deputados: deputados[d.sigla_partido], projetos: 0, autores: {} });
    a.projetos += d.qtd; a.autores[d.nome] = (a.autores[d.nome] || 0) + d.qtd;
  }
  for (const a of Object.values(agg)) [a.maior, a.maiorQtd] = Object.entries(a.autores).sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))[0];
  const valor = (a) => (porDep ? Math.round((10 * a.projetos) / a.deputados) / 10 : a.projetos);
  const ps = Object.values(agg).sort((a, b) => valor(b) - valor(a));
  const totalProjetos = ps.reduce((t, a) => t + a.projetos, 0);
  if (!ps.length) { vazioEm('graf-projetos'); return; }
  const formatter = porDep ? fmt.num1 : fmt.num;
  const el = document.getElementById('graf-projetos'); el.classList.remove('skeleton');
  montar(el, (t) => {
    const op = barras({ categorias: ps.map((a) => a.sigla), horizontal: true, rotulo: true, formatter, gradiente: 'invertido',
                        series: [{ name: porDep ? 'Projetos por deputado' : 'Projetos', data: ps.map(valor) }] })(t);
    op.yAxis.axisLabel = { ...op.yAxis.axisLabel, formatter: (s) => `${s} (${fmt.num(agg[s].deputados)})` };
    // no modo Total, cada barra mostra também a fatia do total de projetos (dos temas filtrados)
    if (!porDep) {
      op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.num(x.value)} (${fmt.pct((100 * x.value) / totalProjetos)})` };
      op.grid = { ...op.grid, right: 104 };  // espaço para o rótulo mais longo ("707 (24,3%)")
    }
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (xs) => {
      const a = agg[xs[0].name];
      return `<b>${fmt.escapar(a.sigla)}</b> · ${fmt.num(a.deputados)} ${a.deputados === 1 ? 'deputado' : 'deputados'}`
        + `<br>Projetos: <b>${fmt.num(a.projetos)}</b> (${fmt.pct((100 * a.projetos) / totalProjetos)} do total) · ${fmt.num1(a.projetos / a.deputados)} por deputado`
        + `<br>Maior autor: ${fmt.escapar(a.maior)} (${fmt.num(a.maiorQtd)}, ${fmt.pct((100 * a.maiorQtd) / a.projetos)} do partido)`;
    } };
    return op;
  }, { tabela: { colunas: ['Partido', 'Deputados', 'Projetos', '% do total', 'Por deputado', 'Maior autor'],
                 linhas: ps.map((a) => [a.sigla, a.deputados, a.projetos, fmt.pct((100 * a.projetos) / totalProjetos), fmt.num1(a.projetos / a.deputados), `${a.maior} (${a.maiorQtd})`]) } });
}
document.querySelectorAll('#projetos-modo button').forEach((b) => b.addEventListener('click', () => {
  modoProjetos = b.dataset.modo;
  document.querySelectorAll('#projetos-modo button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  desenharProjetos();
}));

function desenharSetores() {
  const porSetor = {};
  for (const d of setores) if (passa(d.tema)) porSetor[d.setor] = (porSetor[d.setor] || 0) + d.qtd;
  const ordem = Object.entries(porSetor).sort((a, b) => b[1] - a[1]);
  if (!ordem.length) { vazioEm('graf-setores'); return; }
  const el = document.getElementById('graf-setores');
  el.classList.remove('skeleton');
  montar(el, barras({ gradiente: 'invertido', categorias: ordem.map((d) => d[0]), horizontal: true, series: [{ name: 'Menções', data: ordem.map((d) => d[1]) }], rotulo: true }),
    { tabela: { colunas: ['Setor', 'Menções'], linhas: ordem } });
}

await seguro(document.getElementById('graf-tramitacao'), desenharTramitacao);
await seguro(document.getElementById('graf-projetos'), desenharProjetos);
await seguro(document.getElementById('graf-setores'), desenharSetores);

estado.aoMudar((novo) => {
  filtro = novo; desenharFiltro(); desenharArea(); desenharTreemap(); desenharTabela();
  desenharTramitacao(); desenharProjetos(); desenharSetores();
});
