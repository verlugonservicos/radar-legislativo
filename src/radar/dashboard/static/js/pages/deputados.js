// Deputados: mapa por UF, ranking de atividade, tabela e perfil em drawer.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, GRADIENTE, montar } from '../charts.js';
import { abrirDrawer, Tabela } from '../ui.js';
import * as estado from '../state.js';
import * as fmt from '../format.js';

/* global echarts */
await iniciar();
const deps = await dados('deputados');
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

const nomeUf = Object.fromEntries(geo.features.map((f) => [f.properties.sigla, f.properties.nome]));

/** Indicadores de um grupo de deputados (UF ou região), já respeitando o filtro de partido. */
function resumir(ls) {
  const n = ls.length;
  const comPresenca = ls.filter((d) => d.presenca_votacoes_pct !== null);
  return n ? {
    deputados: n,
    gasto_total: ls.reduce((a, d) => a + (d.gasto_total || 0), 0),
    gasto_por_deputado: ls.reduce((a, d) => a + (d.gasto_total || 0), 0) / n,
    score_atividade_medio: ls.reduce((a, d) => a + (d.score_atividade || 0), 0) / n,
    presenca_votacoes_media: comPresenca.length ? comPresenca.reduce((a, d) => a + d.presenca_votacoes_pct, 0) / comPresenca.length : null,
  } : { deputados: 0, gasto_total: 0, gasto_por_deputado: null, score_atividade_medio: null, presenca_votacoes_media: null };
}
const doPartido = () => deps.filter((d) => !selPartido.value || d.sigla_partido === selPartido.value);
const porUfFiltrado = () => Object.fromEntries(Object.keys(regiaoDe).map((uf) => [uf, resumir(doPartido().filter((d) => d.sigla_uf === uf))]));
const porRegiao = () => Object.keys(REGIOES).map((regiao) => ({
  regiao, ...resumir(doPartido().filter((d) => regiaoDe[d.sigla_uf] === regiao)),
}));

/** Etiqueta do mapa: quantidade de deputados + todos os indicadores (o do mapa em destaque). */
function etiqueta(titulo, sub, a) {
  const partido = selPartido.value ? ` do ${fmt.escapar(selPartido.value)}` : '';
  if (!a.deputados) return `<b>${titulo}</b>${sub}<br>Nenhum deputado${partido} em exercício`;
  const linhas = Object.entries(METRICAS).filter(([k]) => k !== 'deputados').map(([k, [rot, f]]) => {
    const txt = `${rot}: ${f(a[k])}`;
    return k === selMetrica.value ? `<b>${txt}</b>` : txt;
  });
  return `<b>${titulo}</b>${sub}<br><b>${fmt.num(a.deputados)} deputado${a.deputados > 1 ? 's' : ''}${partido}</b> em exercício<br>${linhas.join('<br>')}`;
}

/** Interpola entre duas cores #RRGGBB (t de 0 a 1). */
function misturar(c1, c2, t) {
  const a = c1.match(/\w\w/g).map((h) => parseInt(h, 16)); const b = c2.match(/\w\w/g).map((h) => parseInt(h, 16));
  return `#${a.map((v, i) => Math.round(v + (b[i] - v) * t).toString(16).padStart(2, '0')).join('')}`;
}

// Mesma regra de cores do ranking: maior = verde, menor = vermelho (âmbar no meio).
// Exceção: gasto por deputado segue a regra da página de Despesas (maior = vermelho).
const coresDe = (metrica) => (metrica === 'gasto_por_deputado' ? GRADIENTE : [...GRADIENTE].reverse());
const cor3 = (cores, t) => (t < 0.5 ? misturar(cores[0], cores[1], t * 2) : misturar(cores[1], cores[2], (t - 0.5) * 2));

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
    const ufs = porUfFiltrado();
    const vs = Object.values(ufs).map((a) => a[metrica]).filter((v) => v !== null && v !== undefined);
    // a UF filtrada fica destacada pela própria seleção do filtro (o 2º clique desmarca de verdade)
    mapa = montar(limpa('graf-mapa'), (t) => ({
      tooltip: { trigger: 'item', formatter: (p) => etiqueta(`${nomeUf[p.name]} (${p.name})`, '', ufs[p.name]) },
      visualMap: { min: vs.length ? Math.min(...vs) : 0, max: vs.length ? Math.max(...vs) : 1, ...legenda, calculable: true,
        text: ['maior', 'menor'], inRange: { color: coresDe(metrica) }, textStyle: { color: t.muted }, formatter },
      series: [{ ...serieBase, selectedMode: false,
        data: Object.keys(ufs).map((uf) => ({
          name: uf, value: ufs[uf][metrica] ?? '-',
          ...(uf === selUf.value ? { itemStyle: { borderColor: t.text, borderWidth: 2.5 }, label: { color: t.text, fontWeight: 700 } } : {}),
        })),
        itemStyle: { borderColor: t.surface, borderWidth: 1, areaColor: t.grid },
        emphasis: { label: { show: true, color: t.text }, itemStyle: { areaColor: t.warning } },
        label: { show: true, fontSize: 10, color: t.muted } }],
    }), { tabela: { colunas: ['UF', 'Deputados', rotulo],
                    linhas: Object.entries(ufs).map(([uf, a]) => [uf, a.deputados, formatter(a[metrica])]) } });
    mapa.instancia.on('click', (p) => { selUf.value = selUf.value === p.name ? '' : p.name; aplicar(); });
    return;
  }
  // modo região: cada UF recebe a cor da sua região (bordas internas na mesma cor "fundem" os estados);
  // os rótulos são etiquetas posicionadas no centro geográfico de cada região (scatter sobre o geo).
  const regs = porRegiao();
  const vs = regs.map((r) => r[metrica]).filter((v) => v !== null);
  const [min, max] = vs.length ? [Math.min(...vs), Math.max(...vs)] : [0, 1];
  const valorDe = Object.fromEntries(regs.map((r) => [r.regiao, r[metrica]]));
  const resumoDe = Object.fromEntries(regs.map((r) => [r.regiao, r]));
  mapa = montar(limpa('graf-mapa'), (t) => {
    const hex = (c, alt) => (/^#[0-9a-f]{6}$/i.test(c) ? c : alt);
    const fundo = hex(t.grid, '#E2E8F0'); const texto = hex(t.text, '#0F172A');
    const cor = (v) => cor3(coresDe(metrica), max > min ? (v - min) / (max - min) : 1);
    const borda = (c) => misturar(c, texto, 0.18);
    return {
      tooltip: { trigger: 'item' },
      geo: {
        map: 'BR', roam: false, nameProperty: 'sigla', top: 4, bottom: 4, left: 4, right: 4,
        label: { show: false }, emphasis: { disabled: true }, select: { disabled: true },
        tooltip: { show: true, formatter: (p) => { const r = regiaoDe[p.name]; return etiqueta(r, ` (${REGIOES[r].join(', ')})`, resumoDe[r]); } },
        regions: Object.keys(regiaoDe).map((uf) => {
          const v = valorDe[regiaoDe[uf]]; const c = v === null ? fundo : cor(v);
          return { name: uf, itemStyle: { areaColor: c, borderColor: borda(c), borderWidth: 0.5 } };
        }),
      },
      series: [{
        type: 'scatter', coordinateSystem: 'geo', symbolSize: 1, itemStyle: { color: 'transparent' }, z: 5,
        tooltip: { formatter: (p) => etiqueta(p.name, ` (${REGIOES[p.name].join(', ')})`, resumoDe[p.name]) },
        data: Object.entries(CENTRO_REGIAO).map(([r, coord]) => ({ name: r, value: [...coord, valorDe[r]] })),
        label: {
          show: true, position: 'inside', formatter: (p) => `{r|${p.name}}\n{v|${formatter(p.value[2])}}\n{d|${fmt.num(resumoDe[p.name].deputados)} dep.}`,
          backgroundColor: t.surface, borderColor: t.border, borderWidth: 1, borderRadius: 8, padding: [6, 10],
          shadowColor: 'rgba(15,23,42,.18)', shadowBlur: 6, align: 'center', lineHeight: 18,
          rich: { r: { fontWeight: 700, fontSize: 13, color: t.text, align: 'center' },
                  v: { fontSize: 13, color: t.accent, fontWeight: 700, align: 'center' },
                  d: { fontSize: 11, color: t.muted, align: 'center' } },
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
    gradiente: 'invertido', categorias: top.map((d) => `${d.nome} (${d.sigla_partido}-${d.sigla_uf})`), horizontal: true, rotulo: true, formatter: fmt.num1,
    series: [{ name: 'Score de atividade', data: top.map((d) => d.score_atividade) }],
  }));
}

// Gastos da cota (mesmo critério do mapa para gasto: maior = vermelho), respeitando partido e UF
let gastoPartido; let gastoDeputado;
function desenharGastos() {
  const ls = deps.filter(passa);
  const porPartido = new Map();
  for (const d of ls) porPartido.set(d.sigla_partido, (porPartido.get(d.sigla_partido) || 0) + (d.gasto_total || 0));
  const partidos = [...porPartido].sort((a, b) => b[1] - a[1]);
  const qtd = (sigla) => ls.filter((d) => d.sigla_partido === sigla).length;
  gastoPartido = montar(limpa('graf-gasto-partido'), (t) => ({
    ...barras({ categorias: partidos.map(([p]) => p), horizontal: true, rotulo: true, formatter: fmt.brl, gradiente: true,
                series: [{ name: 'Gasto da cota', data: partidos.map(([, v]) => Math.round(v)) }] })(t),
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => `<b>${fmt.escapar(ps[0].name)}</b><br>Gasto: ${fmt.brlCheio(ps[0].value)}<br>${fmt.num(qtd(ps[0].name))} deputados · ${fmt.brl(ps[0].value / qtd(ps[0].name))} por deputado` },
  }), { tabela: { colunas: ['Partido', 'Deputados', 'Gasto da cota'], linhas: partidos.map(([p, v]) => [p, qtd(p), fmt.brlCheio(v)]) } });
  const top = [...ls].sort((a, b) => (b.gasto_total || 0) - (a.gasto_total || 0)).slice(0, 20);
  gastoDeputado = montar(limpa('graf-gasto-deputado'), barras({
    categorias: top.map((d) => `${d.nome} (${d.sigla_partido}-${d.sigla_uf})`), horizontal: true, rotulo: true, formatter: fmt.brl,
    gradiente: true, series: [{ name: 'Gasto da cota', data: top.map((d) => Math.round(d.gasto_total || 0)) }],
  }), { tabela: { colunas: ['Deputado', 'Partido', 'UF', 'Gasto da cota'], linhas: top.map((d) => [d.nome, d.sigla_partido, d.sigla_uf, fmt.brlCheio(d.gasto_total)]) } });
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
  desenharMapa(); desenharRanking(); desenharGastos(); desenharTabela();
}
selPartido.addEventListener('change', aplicar);
selUf.addEventListener('change', aplicar);
selMetrica.addEventListener('change', desenharMapa);

await seguro(document.getElementById('graf-mapa'), desenharMapa);
await seguro(document.getElementById('graf-ranking'), desenharRanking);
await seguro(document.getElementById('graf-gasto-partido'), desenharGastos);
await seguro(document.getElementById('tabela-deputados'), desenharTabela);
