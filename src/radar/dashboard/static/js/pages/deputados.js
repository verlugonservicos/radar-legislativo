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

// UF → região (IBGE) e a UF que recebe o rótulo da região no mapa
const REGIOES = {
  Norte: ['AC', 'AM', 'AP', 'PA', 'RO', 'RR', 'TO'],
  Nordeste: ['AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE'],
  'Centro-Oeste': ['DF', 'GO', 'MS', 'MT'],
  Sudeste: ['ES', 'MG', 'RJ', 'SP'],
  Sul: ['PR', 'RS', 'SC'],
};
// centro aproximado de cada região (longitude, latitude) para a etiqueta
const CENTRO_REGIAO = { Norte: [-60.5, -4.5], Nordeste: [-40.8, -8.0], 'Centro-Oeste': [-53.5, -15.0], Sudeste: [-45.5, -20.3], Sul: [-51.8, -27.3] };
const regiaoDe = Object.fromEntries(Object.entries(REGIOES).flatMap(([r, ufs]) => ufs.map((u) => [u, r])));

/** Agrega as UFs por região: somas para deputados/gastos, médias ponderadas pelos deputados. */
function porRegiao() {
  return Object.keys(REGIOES).map((regiao) => {
    const ufs = porUf.filter((u) => regiaoDe[u.sigla_uf] === regiao);
    const dep = ufs.reduce((a, u) => a + u.deputados, 0);
    const pond = (k) => ufs.reduce((a, u) => a + (u[k] || 0) * u.deputados, 0) / dep;
    return {
      regiao, deputados: dep, gasto_por_deputado: ufs.reduce((a, u) => a + u.gasto_total, 0) / dep,
      score_atividade_medio: pond('score_atividade_medio'), presenca_votacoes_media: pond('presenca_votacoes_media'),
    };
  });
}

/** Interpola entre duas cores #RRGGBB (t de 0 a 1). */
function misturar(c1, c2, t) {
  const a = c1.match(/\w\w/g).map((h) => parseInt(h, 16)); const b = c2.match(/\w\w/g).map((h) => parseInt(h, 16));
  return `#${a.map((v, i) => Math.round(v + (b[i] - v) * t).toString(16).padStart(2, '0')).join('')}`;
}

let modoMapa = 'uf';
document.querySelectorAll('#mapa-agrupamento button').forEach((b) => b.addEventListener('click', () => {
  modoMapa = b.dataset.modo;
  document.querySelectorAll('#mapa-agrupamento button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  desenharMapa();
}));

function desenharMapa() {
  const [rotulo, formatter] = METRICAS[selMetrica.value];
  const metrica = selMetrica.value;
  const base = { type: 'map', map: 'BR', roam: false, nameProperty: 'sigla',
                 top: 4, bottom: 4, left: 4, right: 4 };  // preenche a área (que tem a proporção do Brasil, 4:5)
  if (modoMapa === 'uf') {
    // tela estreita: legenda na horizontal, abaixo do mapa (não cobre os estados)
    const estreito = document.getElementById('graf-mapa').clientWidth < 480;
    const serieBase = estreito ? { ...base, bottom: 52 } : base;
    const legenda = estreito ? { orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 160 }
      : { left: 0, bottom: 8, itemHeight: 100, itemWidth: 14 };
    const valores = porUf.map((u) => ({ name: u.sigla_uf, value: u[metrica] }));
    const vs = valores.map((v) => v.value);
    mapa = montar(limpa('graf-mapa'), (t) => ({
      tooltip: { trigger: 'item', formatter: (p) => `<b>${p.name}</b><br>${rotulo}: ${formatter(p.value)}` },
      visualMap: { min: Math.min(...vs), max: Math.max(...vs), ...legenda, calculable: true, text: ['maior', 'menor'],
        inRange: { color: [t.grid, t.accent] }, textStyle: { color: t.muted }, formatter },
      series: [{ ...serieBase, data: valores, selectedMode: 'single',
        itemStyle: { borderColor: t.surface, borderWidth: 1, areaColor: t.grid },
        emphasis: { label: { show: true, color: t.text }, itemStyle: { areaColor: t.warning } },
        select: { label: { show: true, color: t.text }, itemStyle: { areaColor: t.warning } },
        label: { show: true, fontSize: 10, color: t.muted } }],
    }), { tabela: { colunas: ['UF', rotulo], linhas: porUf.map((u) => [u.sigla_uf, formatter(u[metrica])]) } });
    mapa.instancia.on('click', (p) => { selUf.value = selUf.value === p.name ? '' : p.name; aplicar(); });
    return;
  }
  // modo região: cada UF recebe a cor da sua região (bordas internas na mesma cor "fundem" os estados);
  // os rótulos são etiquetas posicionadas no centro geográfico de cada região (scatter sobre o geo).
  const regs = porRegiao();
  const vs = regs.map((r) => r[metrica]);
  const [min, max] = [Math.min(...vs), Math.max(...vs)];
  const valorDe = Object.fromEntries(regs.map((r) => [r.regiao, r[metrica]]));
  mapa = montar(limpa('graf-mapa'), (t) => {
    const hex = (c, alt) => (/^#[0-9a-f]{6}$/i.test(c) ? c : alt);
    const fundo = hex(t.grid, '#E2E8F0'); const forte = hex(t.accent, '#4F46E5'); const texto = hex(t.text, '#0F172A');
    // a menor região já começa com 30% da cor de destaque: nunca some no fundo do card
    const cor = (v) => misturar(fundo, forte, 0.3 + 0.7 * (max > min ? (v - min) / (max - min) : 1));
    const borda = (c) => misturar(c, texto, 0.18);
    return {
      tooltip: { trigger: 'item' },
      geo: {
        map: 'BR', roam: false, nameProperty: 'sigla', top: 4, bottom: 4, left: 4, right: 4,
        label: { show: false }, emphasis: { disabled: true }, select: { disabled: true },
        tooltip: { show: true, formatter: (p) => { const r = regiaoDe[p.name]; return `<b>${r}</b> (${REGIOES[r].join(', ')})<br>${rotulo}: ${formatter(valorDe[r])}`; } },
        regions: Object.keys(regiaoDe).map((uf) => {
          const c = cor(valorDe[regiaoDe[uf]]);
          return { name: uf, itemStyle: { areaColor: c, borderColor: borda(c), borderWidth: 0.5 } };
        }),
      },
      series: [{
        type: 'scatter', coordinateSystem: 'geo', symbolSize: 1, itemStyle: { color: 'transparent' }, z: 5,
        tooltip: { formatter: (p) => `<b>${p.name}</b> (${REGIOES[p.name].join(', ')})<br>${rotulo}: ${formatter(valorDe[p.name])}` },
        data: Object.entries(CENTRO_REGIAO).map(([r, coord]) => ({ name: r, value: [...coord, valorDe[r]] })),
        label: {
          show: true, position: 'inside', formatter: (p) => `{r|${p.name}}\n{v|${formatter(p.value[2])}}`,
          backgroundColor: t.surface, borderColor: t.border, borderWidth: 1, borderRadius: 8, padding: [6, 10],
          shadowColor: 'rgba(15,23,42,.18)', shadowBlur: 6, align: 'center', lineHeight: 18,
          rich: { r: { fontWeight: 700, fontSize: 13, color: t.text, align: 'center' },
                  v: { fontSize: 13, color: t.accent, fontWeight: 700, align: 'center' } },
        },
      }],
    };
  }, { tabela: { colunas: ['Região', 'UFs', 'Deputados', rotulo],
                 linhas: regs.map((r) => [r.regiao, REGIOES[r.regiao].join(', '), r.deputados, formatter(r[metrica])]) } });
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
