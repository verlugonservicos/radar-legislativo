// Deputados: mapa por UF, ranking de atividade, tabela e perfil em drawer.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, montar } from '../charts.js';
import { abrirDrawer, Tabela } from '../ui.js';
import * as estado from '../state.js';
import * as fmt from '../format.js';

/* global echarts */
await iniciar();
const deps = await dados('deputados');
const porUf = await dados('deputados_uf');
let filtro = estado.ler();
const selPartido = document.getElementById('f-partido');
const selUf = document.getElementById('f-uf');
const selMetrica = document.getElementById('f-metrica');
for (const p of [...new Set(deps.map((d) => d.sigla_partido))].sort()) selPartido.add(new Option(p, p));
for (const u of [...new Set(deps.map((d) => d.sigla_uf))].sort()) selUf.add(new Option(u, u));
selPartido.value = filtro.partidos[0] || ''; selUf.value = filtro.ufs[0] || '';
const passa = (d) => (!selPartido.value || d.sigla_partido === selPartido.value) && (!selUf.value || d.sigla_uf === selUf.value);
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };

const METRICAS = {
  score_atividade_medio: ['Score de atividade médio', fmt.num1],
  gasto_por_deputado: ['Gasto por deputado', fmt.brl],
  presenca_votacoes_media: ['Presença média em votações', fmt.pct],
  deputados: ['Deputados', fmt.num],
};
let mapa; let ranking; let tabela;
const geo = await fetch('static/geo/brasil-ufs.json').then((r) => r.json());
echarts.registerMap('BR', geo);

function desenharMapa() {
  mapa?.instancia.dispose();
  const [rotulo, formatter] = METRICAS[selMetrica.value];
  const valores = porUf.map((u) => ({ name: u.sigla_uf, value: u[selMetrica.value] }));
  const vs = valores.map((v) => v.value);
  mapa = montar(limpa('graf-mapa'), (t) => ({
    tooltip: { trigger: 'item', formatter: (p) => `<b>${p.name}</b><br>${rotulo}: ${formatter(p.value)}` },
    visualMap: { min: Math.min(...vs), max: Math.max(...vs), left: 8, bottom: 8, calculable: true, text: ['maior', 'menor'],
      inRange: { color: [t.soft, t.accent] }, textStyle: { color: t.muted }, formatter },
    series: [{ type: 'map', map: 'BR', roam: false, nameProperty: 'sigla', data: valores, selectedMode: 'single',
      itemStyle: { borderColor: t.surface, borderWidth: 1, areaColor: t.grid },
      emphasis: { label: { show: true, color: t.text }, itemStyle: { areaColor: t.warning } },
      select: { label: { show: true, color: t.text }, itemStyle: { areaColor: t.warning } },
      label: { show: true, fontSize: 9, color: t.muted } }],
  }), { tabela: { colunas: ['UF', rotulo], linhas: porUf.map((u) => [u.sigla_uf, formatter(u[selMetrica.value])]) } });
  mapa.instancia.on('click', (p) => { selUf.value = selUf.value === p.name ? '' : p.name; aplicar(); });
}

function desenharRanking() {
  ranking?.instancia.dispose();
  const top = deps.filter(passa).slice(0, 20);
  ranking = montar(limpa('graf-ranking'), barras({
    categorias: top.map((d) => `${d.nome} (${d.sigla_partido}-${d.sigla_uf})`), horizontal: true, rotulo: true, formatter: fmt.num1,
    series: [{ name: 'Score de atividade', data: top.map((d) => d.score_atividade) }],
  }));
}

function perfil(d) {
  abrirDrawer(`<div class="person"><img class="avatar" style="width:72px;height:72px" src="${fmt.escapar(d.url_foto)}" alt="" loading="lazy">
    <div><h2>${fmt.escapar(d.nome)}</h2><p class="muted">${fmt.escapar(d.sigla_partido)} · ${fmt.escapar(d.sigla_uf)}</p></div></div>
    <h3>Atividade</h3><dl class="kv">
      <dt>Score de atividade</dt><dd>${fmt.num1(d.score_atividade)} / 100</dd>
      <dt>Autorias</dt><dd>${fmt.num(d.autorias)} proposições</dd>
      <dt>Presença em votações</dt><dd>${fmt.pct(d.presenca_votacoes_pct)} das nominais do Plenário</dd>
      <dt>Presenças em eventos</dt><dd>${fmt.num(d.presencas_eventos)}</dd>
      <dt>Discursos</dt><dd>${fmt.num(d.discursos)}</dd></dl>
    <h3>Comportamento nas votações</h3><dl class="kv">
      <dt>Votos registrados</dt><dd>${fmt.num(d.votos)}</dd>
      <dt>Fidelidade ao partido</dt><dd>${fmt.pct(d.fidelidade_pct)}</dd>
      <dt>Governismo</dt><dd>${fmt.pct(d.governismo_pct)}</dd></dl>
    <h3>Articulação e gastos</h3><dl class="kv">
      <dt>Frentes parlamentares</dt><dd>${fmt.num(d.qtd_frentes)}</dd>
      <dt>Órgãos (atuais)</dt><dd>${fmt.num(d.qtd_orgaos)}</dd>
      <dt>Cota parlamentar</dt><dd>${fmt.brlCheio(d.gasto_total)} no período carregado</dd></dl>
    <p><a href="https://www.camara.leg.br/deputados/${d.id_deputado}" target="_blank" rel="noopener">Perfil na Câmara<span class="sr-only"> (abre em nova aba)</span></a></p>`, d.nome);
}

function desenharTabela() {
  if (tabela) { tabela.atualizar(); return; }
  tabela = new Tabela(document.getElementById('tabela-deputados'), {
    linhas: deps, nomeCsv: 'deputados', filtroExtra: passa, aoClicar: perfil,
    colunas: [
      { chave: 'nome', titulo: 'Deputado', render: (d) => `<span class="person"><img class="avatar" src="${fmt.escapar(d.url_foto)}" alt="" loading="lazy" width="36" height="36">${fmt.escapar(d.nome)}</span>` },
      { chave: 'sigla_partido', titulo: 'Partido' },
      { chave: 'sigla_uf', titulo: 'UF' },
      { chave: 'score_atividade', titulo: 'Score', num: true, render: (d) => fmt.num1(d.score_atividade) },
      { chave: 'autorias', titulo: 'Autorias', num: true },
      { chave: 'presenca_votacoes_pct', titulo: 'Presença', num: true, render: (d) => fmt.pct(d.presenca_votacoes_pct) },
      { chave: 'fidelidade_pct', titulo: 'Fidelidade', num: true, render: (d) => fmt.pct(d.fidelidade_pct) },
      { chave: 'gasto_total', titulo: 'Cota (R$)', num: true, render: (d) => fmt.brl(d.gasto_total) },
    ],
  });
}

function aplicar() {
  estado.gravar({ partidos: selPartido.value ? [selPartido.value] : [], ufs: selUf.value ? [selUf.value] : [] });
  desenharRanking(); desenharTabela();
}
selPartido.addEventListener('change', aplicar);
selUf.addEventListener('change', aplicar);
selMetrica.addEventListener('change', desenharMapa);

await seguro(document.getElementById('graf-mapa'), desenharMapa);
await seguro(document.getElementById('graf-ranking'), desenharRanking);
await seguro(document.getElementById('tabela-deputados'), desenharTabela);
