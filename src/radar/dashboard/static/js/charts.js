// Gráficos ECharts (SPEC V3 12.2): temas lidos das variáveis CSS, re-render ao trocar o tema,
// ResizeObserver, tooltips em pt-BR e tabela alternativa acessível em <details>.
import * as fmt from './format.js';

/* global echarts */
const montados = new Set();
let coresTemas = {};
export const definirCoresTemas = (temas) => { coresTemas = Object.fromEntries(temas.map((t) => [t.nome, t.cor])); };
export const corTema = (nome) => coresTemas[nome] || '#94A3B8';
export const PALETA = ['#334155', '#0EA5E9', '#F59E0B', '#10B981', '#EC4899', '#0891B2', '#EF4444', '#14B8A6', '#84CC16', '#F97316', '#64748B', '#B45309'];

function css(nome) { return getComputedStyle(document.documentElement).getPropertyValue(nome).trim(); }
function temaAtual() {
  const t = {
    text: css('--text'), muted: css('--text-muted'), grid: css('--chart-grid'), axis: css('--chart-axis'),
    surface: css('--surface'), border: css('--border'), accent: css('--accent'), soft: css('--accent-soft'),
    positive: css('--positive'), negative: css('--negative'), warning: css('--warning'),
  };
  return {
    t,
    echarts: {
      color: [t.accent, ...PALETA.slice(1)],
      backgroundColor: 'transparent',
      textStyle: { fontFamily: css('--font-sans'), color: t.text, textBorderWidth: 0 },
      title: { textStyle: { color: t.text } },
      legend: { textStyle: { color: t.muted }, icon: 'roundRect', itemWidth: 12, itemHeight: 8 },
      tooltip: {
        backgroundColor: t.surface, borderColor: t.border, textStyle: { color: t.text, fontSize: 12 },
        extraCssText: 'box-shadow: 0 4px 16px rgb(15 23 42 / .12); border-radius: 8px;',
      },
      categoryAxis: { axisLine: { lineStyle: { color: t.grid } }, axisTick: { show: false }, axisLabel: { color: t.axis }, splitLine: { show: false } },
      valueAxis: { axisLine: { show: false }, axisLabel: { color: t.axis }, splitLine: { lineStyle: { color: t.grid, type: 'dashed' } } },
      timeAxis: { axisLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.axis }, splitLine: { show: false } },
    },
  };
}

function registrar() {
  const { echarts: tema } = temaAtual();
  echarts.registerTheme('radar', tema);
}

/** Monta um gráfico: `fazerOpcao(t)` recebe as cores do tema e devolve a opção ECharts. */
/** `depois(inst, t)`: chamado após cada desenho (inicial, troca de tema) e redimensionamento — para
 *  sobreposições que dependem da posição calculada pelo ECharts (ex.: totais no sankey). */
export function montar(el, fazerOpcao, { tabela, depois } = {}) {
  if (!el) return null;
  for (const m of montados) {  // o mesmo elemento redesenhado: descarta a instância antiga
    if (m.el === el) { m.instancia.dispose(); m.ro?.disconnect(); montados.delete(m); }
  }
  registrar();
  el.setAttribute('role', 'img');
  let inst = echarts.init(el, 'radar', { renderer: 'canvas' });
  const posDesenho = () => { if (depois) inst.on('finished', function uma() { inst.off('finished', uma); depois(inst, temaAtual().t); }); };
  const desenhar = () => { posDesenho(); inst.setOption(fazerOpcao(temaAtual().t), true); };
  desenhar();
  const ro = new ResizeObserver(() => { posDesenho(); inst.resize(); });
  ro.observe(el);
  const registro = {
    el, ro,
    redesenhar() { inst.dispose(); registrar(); inst = echarts.init(el, 'radar', { renderer: 'canvas' }); desenhar(); },
    get instancia() { return inst; },
  };
  montados.add(registro);
  if (tabela) tabelaAlternativa(el, tabela);
  return registro;
}
export function redesenharTodos() { for (const m of montados) m.redesenhar(); }

/** <details> com a tabela dos dados do gráfico (acessibilidade, SPEC 12.2). */
function tabelaAlternativa(el, { colunas, linhas }) {
  const det = document.createElement('details');
  det.className = 'chart-alt';
  const cab = colunas.map((c) => `<th scope="col">${fmt.escapar(c)}</th>`).join('');
  const corpo = linhas.slice(0, 200).map((l) => `<tr>${l.map((v) => `<td>${fmt.escapar(v)}</td>`).join('')}</tr>`).join('');
  det.innerHTML = `<summary>Ver dados em tabela</summary><div class="table-wrap"><table class="data"><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody></table></div>`;
  const anterior = el.nextElementSibling;
  if (anterior?.classList.contains('chart-alt')) {  // redesenho: substitui, nunca acumula
    det.open = anterior.open;
    anterior.replaceWith(det);
  } else {
    el.after(det);
  }
}

// ------------------------------------------------------------------ fábricas de opções
const grade = { left: 8, right: 16, top: 36, bottom: 8, containLabel: true };
const eixoNum = (formatter = fmt.num) => ({ type: 'value', splitNumber: 4, axisLabel: { formatter, hideOverlap: true } });

export function linhas({ x, series, area = false, formatter = fmt.num, xData = true }) {
  return () => ({
    grid: grade, tooltip: { trigger: 'axis', valueFormatter: formatter },
    legend: { top: 0, left: 0 },
    xAxis: { type: 'category', data: x, boundaryGap: false, axisLabel: xData ? { formatter: (v) => fmt.dataCurta(v) } : {} },
    yAxis: eixoNum(formatter),
    series: series.map((s) => ({ type: 'line', smooth: true, showSymbol: false, areaStyle: area ? { opacity: 0.18 } : undefined, ...s })),
  });
}

// Degradê das barras ordenadas por valor: menor = verde, intermediário = âmbar, maior = vermelho
// (com gradiente: 'invertido', o contrário)
// Modo daltônico (preferência salva; a página recarrega ao alternar): troca verde→âmbar→vermelho pela
// escala divergente azul→areia→laranja (extremos da paleta Okabe-Ito; o meio em areia evita os tons
// esverdeados que surgiriam entre azul e amarelo), distinguível em deuteranopia,
// protanopia e tritanopia (o eixo azul–amarelo é preservado e a luminosidade muda ao longo da escala)
export const DALTONICO = document.documentElement.dataset.cores === 'daltonico';
export const GRADIENTE = DALTONICO ? ['#0072B2', '#D9C27E', '#D55E00'] : ['#16A34A', '#F59E0B', '#DC2626'];
/** Cor do degradê para um valor (mesma escala do visualMap): útil onde não há visualMap, como no treemap. */
export function corGradiente(v, min, max, invertido = false) {
  const cores = (invertido ? [...GRADIENTE].reverse() : GRADIENTE).map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)));
  const f = max > min ? Math.min(1, Math.max(0, (v - min) / (max - min))) * (cores.length - 1) : 0;
  const i = Math.min(cores.length - 2, Math.floor(f)); const r = f - i;
  return `rgb(${cores[i].map((c, k) => Math.round(c + (cores[i + 1][k] - c) * r)).join(',')})`;
}
const valorDe = (d) => (d !== null && typeof d === 'object' ? d.value : d);

export function barras({ categorias, series, horizontal = false, empilhado = false, formatter = fmt.num, rotulo = false, gradiente = false }) {
  return (t = {}) => {
    const cat = { type: 'category', data: categorias, axisLabel: { interval: 0, hideOverlap: true } };
    const val = eixoNum(formatter);
    const comGradiente = Boolean(gradiente);  // o degradê vale para a 1ª série (as demais mantêm a cor própria)
    const vs = comGradiente ? series[0].data.map(valorDe).filter((v) => v !== null && v !== undefined) : [];
    return {
      grid: { ...grade, top: series.length > 1 || comGradiente ? 36 : 12, right: rotulo && horizontal ? 72 : grade.right },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: formatter },
      legend: series.length > 1 ? { top: 0, left: 0 } : undefined,
      visualMap: comGradiente && vs.length ? {
        type: 'continuous', show: true, min: Math.min(...vs), max: Math.max(...vs), seriesIndex: 0,
        dimension: horizontal ? 0 : 1, calculable: false, orient: 'horizontal', right: 0, top: 0,
        itemWidth: 10, itemHeight: 90, text: ['maior', 'menor'], textGap: 6,
        // gradiente: 'invertido' = maior em verde (quando mais é melhor: atividade, participação, membros)
        textStyle: { color: t.muted, fontSize: 11 }, inRange: { color: gradiente === 'invertido' ? [...GRADIENTE].reverse() : GRADIENTE },
      } : undefined,
      xAxis: horizontal ? val : cat, yAxis: horizontal ? { ...cat, inverse: true } : val,
      series: series.map((s) => ({
        type: 'bar', stack: empilhado ? 'total' : undefined, barMaxWidth: 28, itemStyle: { borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
        label: rotulo ? { show: true, position: horizontal ? 'right' : 'top', formatter: (p) => formatter(p.value), fontSize: 11, color: t.muted, textBorderWidth: 0 } : undefined,
        ...s,
      })),
    };
  };
}

export function rosca({ itens, formatter = fmt.num }) {
  return (t) => ({
    tooltip: { trigger: 'item', valueFormatter: formatter },
    legend: { type: 'scroll', orient: 'horizontal', bottom: 0, left: 'center', textStyle: { color: t.muted, fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['48%', '74%'], center: ['50%', '44%'], avoidLabelOverlap: true,
      itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 }, label: { show: false },
      data: itens,
    }],
  });
}

export function sparkline(valores, cor) {
  return (t) => ({
    grid: { left: 0, right: 0, top: 2, bottom: 2 }, xAxis: { type: 'category', show: false, data: valores.map((_, i) => i) },
    yAxis: { type: 'value', show: false, min: 'dataMin' }, tooltip: { show: false },
    series: [{ type: 'line', data: valores, smooth: true, showSymbol: false, lineStyle: { width: 2, color: cor || t.accent }, areaStyle: { opacity: 0.12, color: cor || t.accent } }],
  });
}

// gradiente: true pinta o arco pelo valor (0 = vermelho, metade = âmbar, máximo = verde)
export function gauge({ valor, max = 100, rotulo, formatter = fmt.pct, gradiente = false }) {
  return (t) => ({
    series: [{
      type: 'gauge', startAngle: 210, endAngle: -30, min: 0, max, radius: '95%', center: ['50%', '58%'],
      progress: { show: true, width: 14, roundCap: true, itemStyle: { color: gradiente ? corGradiente(valor, 0, max, true) : t.accent } },
      axisLine: { lineStyle: { width: 14, color: [[1, t.grid]] }, roundCap: true },
      pointer: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      title: { offsetCenter: [0, '38%'], color: t.muted, fontSize: 12 },
      detail: { valueAnimation: true, offsetCenter: [0, '0%'], fontSize: 28, fontWeight: 700, color: t.text, formatter },
      data: [{ value: valor, name: rotulo }],
    }],
  });
}
