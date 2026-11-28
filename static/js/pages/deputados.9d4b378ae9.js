// Deputados: mapa por UF, ranking de atividade, tabela e perfil em drawer.
import { iniciar, seguro } from '../app.3b9094f3e7.js';
import { dados } from '../data.4fb3031e8e.js';
import { GRADIENTE, barras, linhaMedia, mediaDe, montar } from '../charts.83ed569f4b.js';
import { abrirDrawer, notaDivergencia, Tabela, textoLotes, vazio } from '../ui.6a7de658b0.js';
import * as estado from '../state.a9d7c61d1d.js';
import * as fmt from '../format.20a0ca273f.js';

/* global echarts */
await iniciar();
const deps = await dados('deputados');
const projetosPartido = await dados('projetos_partido');
const lotes = await dados('lotes_autoria');
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
// proporção correta do mapa: cosseno da latitude média do país (caixa -33,7° a +5,3° → média -14,2°)
const ASPECTO_BR = 0.969;
// caixa (lng/lat) de cada UF: centro para a etiqueta da UF selecionada e tamanho para saber se cabe dentro
const caixaUf = Object.fromEntries(geo.features.map((f) => {
  const pts = (f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates).flat(2);
  const xs = pts.map((p) => p[0]); const ys = pts.map((p) => p[1]);
  return [f.properties.sigla, [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]];
}));

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

// UF selecionada: etiqueta com o nº de deputados no centro do estado; se o estado é pequeno na tela
// (DF, SE, AL…), a etiqueta vai para o lado (mar, a leste) com uma linha-guia até o estado
function etiquetaUfSelecionada(inst, t, ufs) {
  const uf = selUf.value;
  if (!uf || !caixaUf[uf] || !ufs[uf]) { inst.setOption({ graphic: [{ id: 'uf-sel', type: 'group', children: [] }] }, { replaceMerge: ['graphic'] }); return; }
  const [x0, y0, x1, y1] = caixaUf[uf];
  const [ax, ay] = inst.convertToPixel({ seriesIndex: 0 }, [x0, y1]);
  const [bx, by] = inst.convertToPixel({ seriesIndex: 0 }, [x1, y0]);
  const [cx, cy] = inst.convertToPixel({ seriesIndex: 0 }, [(x0 + x1) / 2, (y0 + y1) / 2]);
  const n = ufs[uf].deputados;
  const texto = `${uf} · ${fmt.num(n)} ${n === 1 ? 'deputado' : 'deputados'}`;
  const largura = texto.length * 6.6 + 16; const altura = 24;
  const cabe = Math.abs(bx - ax) > largura + 8 && Math.abs(by - ay) > altura + 8;
  const W = inst.getWidth();
  let lx = cx; let ly = cy;
  if (!cabe) {  // fora do estado: à direita (mar) se couber, senão à esquerda; um pouco acima para não cobrir vizinhos
    lx = Math.max(ax, bx) + 24 + largura / 2 <= W - 4 ? Math.max(ax, bx) + 24 + largura / 2 : Math.min(ax, bx) - 24 - largura / 2;
    ly = cy - 18;
  }
  const filhos = [];
  if (!cabe) filhos.push({ type: 'line', silent: true, z: 100, shape: { x1: cx, y1: cy, x2: lx - Math.sign(lx - cx) * largura / 2, y2: ly }, style: { stroke: t.text, lineWidth: 1 } });
  filhos.push({ type: 'rect', silent: true, z: 100, shape: { x: lx - largura / 2, y: ly - altura / 2, width: largura, height: altura, r: 6 },
                style: { fill: t.surface, stroke: t.border, shadowColor: 'rgba(15,23,42,.18)', shadowBlur: 6 } });
  filhos.push({ type: 'text', silent: true, z: 101, x: lx, y: ly, style: { text: texto, align: 'center', verticalAlign: 'middle', fontSize: 12, fontWeight: 700, fill: t.text } });
  inst.setOption({ graphic: [{ id: 'uf-sel', type: 'group', z: 100, children: filhos }] }, { replaceMerge: ['graphic'] });
}

// Destaques do painel ao lado do mapa: 5 maiores e 5 menores UFs (ou as regiões) na métrica escolhida,
// com a cor da mesma escala do mapa; no modo UF, clicar num item filtra a página por aquela UF
function desenharDestaques(itens, formatter, rotulo, metrica) {
  const el = document.getElementById('destaques-mapa');
  const vs = itens.filter((i) => i.valor !== null && i.valor !== undefined).sort((a, b) => b.valor - a.valor);
  if (!vs.length) { el.innerHTML = ''; return; }
  const [min, max] = [vs[vs.length - 1].valor, vs[0].valor];
  const cor = (v) => cor3(coresDe(metrica), max > min ? (v - min) / (max - min) : 1);
  const item = (i) => `<li>${modoMapa === 'uf' ? `<button type="button" data-uf="${fmt.escapar(i.chave)}">` : '<span>'}`
    + `<span class="barra" style="background:${cor(i.valor)}"></span>${fmt.escapar(i.nome)}${modoMapa === 'uf' ? '</button>' : '</span>'}`
    + `<span class="valor">${formatter(i.valor)}</span></li>`;
  const n = modoMapa === 'uf' ? 5 : 2;
  const totalDeps = itens.reduce((t, i) => t + (i.deputados || 0), 0);
  el.innerHTML = `<p class="painel-mapa__nota">${fmt.escapar(rotulo)} · ${fmt.num(totalDeps)} deputados${selPartido.value ? ` do ${fmt.escapar(selPartido.value)}` : ''}</p>`
    + `<div><h3>Maiores</h3><ol>${vs.slice(0, n).map(item).join('')}</ol></div>`
    + `<div><h3>Menores</h3><ol>${vs.slice(-n).reverse().map(item).join('')}</ol></div>`;
  el.querySelectorAll('button[data-uf]').forEach((b) => b.addEventListener('click', () => {
    selUf.value = selUf.value === b.dataset.uf ? '' : b.dataset.uf; aplicar();
  }));
}

function desenharMapa() {
  const [rotulo, formatter] = METRICAS[selMetrica.value];
  const metrica = selMetrica.value;
  // aspectScale = cos(latitude média do Brasil, -14,2°) ≈ 0,97: o padrão do ECharts (0,75) achatava o país
  // na horizontal (largura/altura 0,75 em vez de 0,97). A área do gráfico é quase quadrada (CSS .chart--mapa).
  // layoutCenter/layoutSize mantêm a proporção (top/left/right/bottom juntos esticariam o mapa até a caixa)
  const base = { type: 'map', map: 'BR', roam: false, nameProperty: 'sigla', aspectScale: ASPECTO_BR,
                 layoutCenter: ['50%', '50%'], layoutSize: '98%' };
  // tela estreita: legenda na horizontal, abaixo do mapa (não cobre os estados)
  const estreito = document.getElementById('graf-mapa').clientWidth < 480;
  const legenda = estreito ? { orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 160 }
    : { left: 0, bottom: 8, itemHeight: 100, itemWidth: 14 };
  if (modoMapa === 'uf') {
    const serieBase = estreito ? { ...base, layoutCenter: ['50%', '45%'], layoutSize: '86%' } : base;
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
          ...(uf === selUf.value ? { itemStyle: { borderColor: t.text, borderWidth: 2.5 }, label: { color: '#0F172A', fontWeight: 800 } } : {}),
        })),
        itemStyle: { borderColor: t.surface, borderWidth: 1, areaColor: t.grid },
        emphasis: { label: { show: true, color: '#0F172A' }, itemStyle: { areaColor: t.warning } },
        // sigla da UF em preto nos dois temas: o fundo é sempre a cor viva da escala (verde/âmbar/vermelho),
        // onde o cinza do tema escuro sumia
        label: { show: true, fontSize: 10, fontWeight: 600, color: '#0F172A' } }],
    }), { tabela: { colunas: ['UF', 'Deputados', rotulo],
                    linhas: Object.entries(ufs).map(([uf, a]) => [uf, a.deputados, formatter(a[metrica])]) },
          depois: (inst, t) => etiquetaUfSelecionada(inst, t, ufs) });
    mapa.instancia.on('click', (p) => { selUf.value = selUf.value === p.name ? '' : p.name; aplicar(); });
    desenharDestaques(Object.entries(ufs).map(([uf, a]) => ({ chave: uf, nome: `${nomeUf[uf]} (${uf})`, valor: a[metrica], deputados: a.deputados })),
                      formatter, rotulo, metrica);
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
      // mesma legenda de cor do mapa por UF (só leitura: as cores das regiões já vêm calculadas acima;
      // o visualMap age apenas sobre os pontos invisíveis das etiquetas; sem alças, os extremos vão no texto)
      visualMap: { min, max, ...legenda, calculable: false, seriesIndex: 0, dimension: 2,
        text: [`maior · ${formatter(max)}`, `menor · ${formatter(min)}`], inRange: { color: coresDe(metrica) }, textStyle: { color: t.muted }, formatter },
      geo: {
        map: 'BR', roam: false, nameProperty: 'sigla', aspectScale: ASPECTO_BR,
        layoutCenter: ['50%', estreito ? '45%' : '50%'], layoutSize: estreito ? '86%' : '98%',
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
  desenharDestaques(regs.map((r) => ({ chave: r.regiao, nome: r.regiao, valor: r[metrica], deputados: r.deputados })), formatter, rotulo, metrica);
}

// Top 20: o gráfico ocupa a altura do card (acompanha o mapa ao lado), com o eixo preso embaixo
const QTD_RANKING = 20;
function desenharRanking() {
  ranking?.instancia.dispose();
  const el = limpa('graf-ranking');
  const top = deps.filter(passa).slice(0, QTD_RANKING);
  ranking = montar(el, (t) => {
    const op = barras({
      gradiente: 'invertido', categorias: top.map((d) => `${d.nome} (${d.sigla_partido}-${d.sigla_uf})`), horizontal: true, rotulo: true, formatter: fmt.num1,
      series: [{ name: 'Score de atividade', data: top.map((d) => d.score_atividade) }],
    })(t);
    // enquadramento: eixo até 100 (o score vai de 0 a 100) e margens laterais justas ao rótulo "97,0"
    op.grid = { ...op.grid, left: 0, right: 44, bottom: 4 };
    op.xAxis = { ...op.xAxis, ...eixoAte(100, 5), axisLabel: { ...op.xAxis.axisLabel, showMaxLabel: true } };  // 0, 20 … 100
    // média de todos os deputados do filtro (não só dos 20 do topo)
    linhaMedia(op, mediaDe(deps.filter(passa).map((d) => d.score_atividade)), t, { formatter: fmt.num1 });
    return op;
  }, { tabela: { colunas: ['Deputado', 'Partido', 'UF', 'Score de atividade'], linhas: top.map((d) => [d.nome, d.sigla_partido, d.sigla_uf, fmt.num1(d.score_atividade)]) } });
}

// Gastos da cota (mesmo critério do mapa para gasto: maior = vermelho), respeitando partido e UF
let gastoPartido; let gastoDeputado;
// eixo X que termina na marca "redonda" logo acima do maior valor (ex.: 536 → 600), com ~4 a 6 marcas:
// a barra maior não encosta na borda e o fim do eixo tem número, sem sensação de vazio
function eixoAte(maior, marcas = 5) {
  const bruto = (maior || 1) / marcas; const ordem = 10 ** Math.floor(Math.log10(bruto));
  const passo = [1, 2, 2.5, 5, 10].map((m) => m * ordem).find((v) => v >= bruto);
  // nível intermediário de escala: linha de grade a cada meio passo (sem número, para não amontoar
  // rótulos) — mais referência no mesmo espaço, sem encolher as barras
  return { min: 0, max: Math.ceil(maior / passo) * passo, interval: passo,
           minorTick: { show: true, splitNumber: 2 }, minorSplitLine: { show: true, lineStyle: { type: 'dashed', opacity: 0.5 } } };
}

function desenharGastos() {
  const ls = deps.filter(passa);
  const porPartido = new Map();
  for (const d of ls) porPartido.set(d.sigla_partido, (porPartido.get(d.sigla_partido) || 0) + (d.gasto_total || 0));
  const partidos = [...porPartido].sort((a, b) => b[1] - a[1]).slice(0, 20);  // Top 20 partidos
  const qtd = (sigla) => ls.filter((d) => d.sigla_partido === sigla).length;
  // % do gasto total dos deputados filtrados, entre parênteses ao lado de cada barra (padrão dos projetos/setores)
  const total = ls.reduce((t, d) => t + (d.gasto_total || 0), 0);
  const pct = (v) => fmt.pct2(total ? (100 * v) / total : 0);  // 2 casas: no Top 20 por deputado, os valores ficam abaixo de 1%
  const comPct = (op, maior, marcas = 4) => {
    op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.brl(x.value)} (${pct(x.value)})` };
    // enquadramento: nomes encostados à esquerda, eixo até o maior valor e margem direita justa ao rótulo
    op.grid = { ...op.grid, left: 0, right: 124 };
    op.xAxis = { ...op.xAxis, ...eixoAte(maior, marcas), axisLabel: { ...op.xAxis.axisLabel, showMaxLabel: true } };
    return op;
  };
  gastoPartido = montar(limpa('graf-gasto-partido'), (t) => {
    const op = comPct(barras({ categorias: partidos.map(([p]) => p), horizontal: true, rotulo: true, formatter: fmt.brl, gradiente: true,
                               series: [{ name: 'Gasto da cota', data: partidos.map(([, v]) => Math.round(v)) }] })(t), partidos[0]?.[1]);
    // nome do partido com o nº de deputados (a categoria continua só a sigla, usada no tooltip)
    op.yAxis.axisLabel = { ...op.yAxis.axisLabel, formatter: (p) => `${p} (${fmt.num(qtd(p))})` };
    linhaMedia(op, mediaDe([...porPartido.values()]), t, { formatter: fmt.brl });  // média de todos os partidos
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => `<b>${fmt.escapar(ps[0].name)}</b><br>Gasto: ${fmt.brlCheio(ps[0].value)} (${pct(ps[0].value)} do total)<br>${fmt.num(qtd(ps[0].name))} deputados · ${fmt.brl(ps[0].value / qtd(ps[0].name))} por deputado` };
    return op;
  }, { tabela: { colunas: ['Partido', 'Deputados', 'Gasto da cota', '% do total'], linhas: partidos.map(([p, v]) => [p, qtd(p), fmt.brlCheio(v), pct(v)]) } });
  const top = [...ls].sort((a, b) => (b.gasto_total || 0) - (a.gasto_total || 0)).slice(0, 20);
  gastoDeputado = montar(limpa('graf-gasto-deputado'), (t) => {
    const op = comPct(barras({
      categorias: top.map((d) => `${d.nome} (${d.sigla_partido}-${d.sigla_uf})`), horizontal: true, rotulo: true, formatter: fmt.brl,
      gradiente: true, series: [{ name: 'Gasto da cota', data: top.map((d) => Math.round(d.gasto_total || 0)) }],
    })(t), top[0]?.gasto_total, 3);
    linhaMedia(op, mediaDe(ls.map((d) => d.gasto_total || 0)), t, { formatter: fmt.brl });  // média de todos os deputados do filtro
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => `<b>${fmt.escapar(ps[0].name)}</b><br>Gasto: ${fmt.brlCheio(ps[0].value)} (${pct(ps[0].value)} do total dos ${fmt.num(ls.length)} deputados)` };
    return op;
  }, { tabela: { colunas: ['Deputado', 'Partido', 'UF', 'Gasto da cota', '% do total'], linhas: top.map((d) => [d.nome, d.sigla_partido, d.sigla_uf, fmt.brlCheio(d.gasto_total), pct(d.gasto_total || 0)]) } });
}

// Top 20 deputados por projetos apresentados (autor principal; mesmo critério do gráfico por partido na
// página de Proposições), respeitando os filtros de partido e UF; o tooltip mostra os temas principais
let projetosDeputado;
function desenharProjetosDeputado() {
  const porDep = {};
  for (const r of projetosPartido) {
    const a = (porDep[r.id_deputado] ??= { total: 0, temas: {} });
    a.total += r.qtd; a.temas[r.tema] = (a.temas[r.tema] || 0) + r.qtd;
  }
  const top = deps.filter((d) => passa(d) && porDep[d.id_deputado])
    .sort((a, b) => porDep[b.id_deputado].total - porDep[a.id_deputado].total || a.nome.localeCompare(b.nome)).slice(0, 20);
  // % do total de projetos de todos os deputados do filtro (não só dos 20), com 2 casas
  const totalProj = deps.filter((d) => passa(d) && porDep[d.id_deputado]).reduce((t, d) => t + porDep[d.id_deputado].total, 0);
  const pctProj = (v) => fmt.pct2(totalProj ? (100 * v) / totalProj : 0);
  const el = limpa('graf-projetos-deputado');
  // nota só quando os autores do lote aparecem no ranking filtrado
  const ids = new Set(top.map((d) => d.id_deputado));
  notaDivergencia(el, textoLotes(lotes.filter((l) => ids.has(l.id_deputado))));
  if (!top.length) { el.innerHTML = vazio(); return; }
  projetosDeputado = montar(el, (t) => {
    const op = barras({ categorias: top.map((d) => `${d.nome} (${d.sigla_partido}-${d.sigla_uf})`), horizontal: true, rotulo: true,
                        gradiente: 'invertido', series: [{ name: 'Projetos', data: top.map((d) => porDep[d.id_deputado].total) }] })(t);
    op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.num(x.value)} (${pctProj(x.value)})` };
    // enquadramento: eixo termina no maior valor (sem a sobra até a próxima marca) e margem direita justa ao
    // rótulo mais longo ("536 (19,51%)"); a esquerda encosta nos nomes
    op.grid = { ...op.grid, left: 0, right: 96 };
    op.xAxis = { ...op.xAxis, ...eixoAte(porDep[top[0].id_deputado].total, 6), axisLabel: { ...op.xAxis.axisLabel, showMaxLabel: true } };
    // média de projetos de todos os deputados do filtro (quem não apresentou conta como zero)
    linhaMedia(op, mediaDe(deps.filter(passa).map((d) => porDep[d.id_deputado]?.total || 0)), t, { formatter: fmt.num1 });
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (xs) => {
      const d = top[xs[0].dataIndex]; const a = porDep[d.id_deputado];
      const temas = Object.entries(a.temas).sort((x, y) => y[1] - x[1]).slice(0, 3)
        .map(([tema, n]) => `${fmt.escapar(tema)}: ${fmt.num(n)}`).join('<br>');
      return `<b>${fmt.escapar(d.nome)}</b> (${fmt.escapar(d.sigla_partido)}-${fmt.escapar(d.sigla_uf)})<br>Projetos: <b>${fmt.num(a.total)}</b> (${pctProj(a.total)} do total)<br><i>Principais temas</i><br>${temas}`;
    } };
    return op;
  }, { tabela: { colunas: ['Deputado', 'Partido', 'UF', 'Projetos', '% do total'], linhas: top.map((d) => [d.nome, d.sigla_partido, d.sigla_uf, porDep[d.id_deputado].total, pctProj(porDep[d.id_deputado].total)]) } });
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
  desenharMapa(); desenharRanking(); desenharProjetosDeputado(); desenharGastos(); desenharTabela();
}
selPartido.addEventListener('change', aplicar);
selUf.addEventListener('change', aplicar);
selMetrica.addEventListener('change', desenharMapa);

await seguro(document.getElementById('graf-mapa'), desenharMapa);
await seguro(document.getElementById('graf-ranking'), desenharRanking);
await seguro(document.getElementById('graf-projetos-deputado'), desenharProjetosDeputado);
await seguro(document.getElementById('graf-gasto-partido'), desenharGastos);
await seguro(document.getElementById('tabela-deputados'), desenharTabela);
