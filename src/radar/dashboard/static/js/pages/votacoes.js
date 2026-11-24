// Votações e Partidos: votações por dia, participação, fidelidade × governismo e concordância.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, montar } from '../charts.js';
import { Tabela } from '../ui.js';
import * as fmt from '../format.js';

await iniciar();
const partidos = await dados('partidos');
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };

await seguro(document.getElementById('graf-dia'), async () => {
  const v = await dados('votacoes_dia');
  montar(limpa('graf-dia'), (t) => barras({
    categorias: v.map((d) => fmt.dataCurta(d.data)), empilhado: true,
    series: [
      { name: 'Aprovadas', data: v.map((d) => d.aprovadas), itemStyle: { color: t.positive } },
      { name: 'Rejeitadas', data: v.map((d) => d.rejeitadas), itemStyle: { color: t.negative } },
      { name: 'Sem resultado', data: v.map((d) => d.total - d.aprovadas - d.rejeitadas), itemStyle: { color: t.grid } },
    ],
  })(t), { tabela: { colunas: ['Data', 'Total', 'Aprovadas', 'Rejeitadas', 'Nominais'], linhas: v.map((d) => [fmt.data(d.data), d.total, d.aprovadas, d.rejeitadas, d.nominais]) } });
});

await seguro(document.getElementById('graf-participacao'), async () => {
  const ps = partidos.filter((p) => p.participacao_pct !== null).sort((a, b) => b.participacao_pct - a.participacao_pct);
  montar(limpa('graf-participacao'), barras({
    categorias: ps.map((p) => p.sigla_partido), horizontal: true, rotulo: true, formatter: fmt.pct,
    series: [{ name: 'Participação', data: ps.map((p) => p.participacao_pct) }],
  }), { tabela: { colunas: ['Partido', 'Participação'], linhas: ps.map((p) => [p.sigla_partido, fmt.pct(p.participacao_pct)]) } });
});

const translucido = (hex, a) => (/^#[0-9a-f]{6}$/i.test(hex)
  ? `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})` : hex);

// grupos pela proximidade com o governo (só para colorir e facilitar a leitura)
const GRUPOS = [
  { nome: 'Alinhados ao governo (≥ 60%)', teste: (g) => g >= 60, cor: (t) => t.accent },
  { nome: 'Intermediários (40–60%)', teste: (g) => g >= 40 && g < 60, cor: (t) => t.warning },
  { nome: 'Distantes do governo (< 40%)', teste: (g) => g < 40, cor: (t) => t.negative },
];

await seguro(document.getElementById('graf-dispersao'), async () => {
  const ps = partidos.filter((p) => p.fidelidade_pct !== null && p.governismo_pct !== null);
  const maxDep = Math.max(...ps.map((p) => p.deputados));
  const minX = Math.max(0, Math.floor((Math.min(...ps.map((p) => p.fidelidade_pct)) - 3) / 5) * 5);
  const elDisp = limpa('graf-dispersao');
  const COLUNA = 130;  // margem direita: coluna de nomes do aglomerado perto de 100% de fidelidade
  montar(elDisp, (t) => ({
    grid: { left: 20, right: COLUNA, top: 48, bottom: 36, containLabel: true },
    legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, icon: 'circle' },
    tooltip: { formatter: (p) => `<b>${fmt.escapar(p.data[3])}</b> · ${fmt.num(p.data[2])} deputados<br>Fidelidade ao partido: ${fmt.pct(p.data[0])}<br>Governismo: ${fmt.pct(p.data[1])}` },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'inside', yAxisIndex: 0, filterMode: 'none' }],
    xAxis: { type: 'value', name: 'Fidelidade ao partido (%)', nameLocation: 'middle', nameGap: 26, min: minX, max: 101.5,
      axisLabel: { showMaxLabel: false }, nameTextStyle: { color: t.muted } },
    yAxis: { type: 'value', name: 'Governismo (%)', nameLocation: 'middle', nameRotate: 90, nameGap: 36, max: 102,
      min: Math.max(0, Math.floor((Math.min(...ps.map((p) => p.governismo_pct)) - 6) / 10) * 10),
      axisLabel: { showMaxLabel: false }, nameTextStyle: { color: t.muted } },
    series: GRUPOS.map((g, k) => ({
      type: 'scatter', name: g.nome,
      data: ps.filter((p) => g.teste(p.governismo_pct)).map((p) => [p.fidelidade_pct, p.governismo_pct, p.deputados, p.sigla_partido]),
      symbolSize: (d) => 8 + 30 * Math.sqrt(d[2] / maxDep),
      itemStyle: { color: g.cor(t), opacity: 0.55, borderColor: g.cor(t), borderWidth: 1.5 },
      emphasis: { focus: 'self', itemStyle: { opacity: 0.9 } },
      label: { show: true, formatter: (p) => p.data[3], position: 'top', distance: 3, fontSize: 11, fontWeight: 600, color: t.text,
        backgroundColor: translucido(t.surface, 0.85), padding: [1, 4], borderRadius: 4 },  // legível mesmo sobre outra bolha
      labelLine: { show: true, length2: 4, lineStyle: { color: t.muted, width: 0.8 } },
      // perto da borda direita: o nome vai para uma coluna fora da área do gráfico, ligado por uma linha-guia
      labelLayout: (p) => (p.rect.x + p.rect.width / 2 > elDisp.clientWidth - COLUNA - 70
        ? { x: elDisp.clientWidth - COLUNA + 14, align: 'left', moveOverlap: 'shiftY' }
        : { moveOverlap: 'shiftY' }),
      markLine: k === 0 ? { silent: true, symbol: 'none', lineStyle: { color: t.muted, type: 'dashed', width: 1 },
        label: { formatter: '50%', color: t.muted, fontSize: 10, position: 'insideStartTop' }, data: [{ yAxis: 50 }] } : undefined,
    })),
  }), { tabela: { colunas: ['Partido', 'Deputados', 'Fidelidade', 'Governismo'], linhas: ps.map((p) => [p.sigla_partido, p.deputados, fmt.pct(p.fidelidade_pct), fmt.pct(p.governismo_pct)]) } });
});

await seguro(document.getElementById('graf-heatmap'), async () => {
  const sim = await dados('similaridade_partidos');
  // ordem por governismo: governo e oposição aparecem como blocos
  const ordem = [...partidos].sort((a, b) => (b.governismo_pct ?? -1) - (a.governismo_pct ?? -1))
    .map((p) => p.sigla_partido).filter((s) => sim.some((d) => d.partido_a === s));
  const fora = sim.filter((d) => ordem.includes(d.partido_a) && ordem.includes(d.partido_b) && d.partido_a !== d.partido_b);
  const vmin = Math.max(0, Math.floor(Math.min(...fora.map((d) => d.concordancia_pct)) / 10) * 10);
  const meio = (v) => { const x = (v - vmin) / (100 - vmin); return x > 0.3 && x < 0.7; };  // faixa âmbar: texto escuro
  // a matriz é simétrica: só o triângulo de baixo (cada par aparece uma vez). Colunas = todos menos o
  // último; linhas = todos menos o primeiro — assim não sobram linha nem coluna vazias.
  const colunas = ordem.slice(0, -1); const linhasY = ordem.slice(1);
  const pontos = fora.filter((d) => ordem.indexOf(d.partido_b) > ordem.indexOf(d.partido_a)).map((d) => ({
    value: [colunas.indexOf(d.partido_a), linhasY.indexOf(d.partido_b), d.concordancia_pct, d.votacoes_comuns],
    label: { color: meio(d.concordancia_pct) ? '#1F2937' : '#FFFFFF' },
  }));
  const el = limpa('graf-heatmap');
  montar(el, (t) => ({
    grid: { left: 8, right: 8, top: 8, bottom: 8, containLabel: true },
    tooltip: { formatter: (p) => `${fmt.escapar(colunas[p.data.value[0]])} × ${fmt.escapar(linhasY[p.data.value[1]])}: <b>${fmt.pct(p.data.value[2])}</b><br>${fmt.num(p.data.value[3])} votações em comum` },
    xAxis: { type: 'category', data: colunas, position: 'bottom', axisLabel: { rotate: 60, fontSize: 10, interval: 0 }, splitArea: { show: false } },
    yAxis: { type: 'category', data: linhasY, inverse: true, axisLabel: { fontSize: 10, interval: 0 } },
    // dimensão 2 = % de concordância (a 3 é o nº de votações em comum)
    visualMap: { seriesIndex: 0, dimension: 2, min: vmin, max: 100, calculable: false, orient: 'vertical', right: 8, top: 8,
      itemWidth: 14, itemHeight: 160, text: ['100% votam igual', `${vmin}%`], textGap: 8,
      inRange: { color: ['#DC2626', '#F59E0B', '#4F46E5'] }, textStyle: { color: t.muted } },
    series: [
      { type: 'heatmap', data: pontos, itemStyle: { borderColor: t.surface, borderWidth: 1 },
        label: { show: el.clientWidth >= 420, formatter: (p) => Math.round(p.data.value[2]), fontSize: 9 },
        emphasis: { focus: 'self', itemStyle: { borderColor: t.text, borderWidth: 2 } } },
    ],
  }), { tabela: { colunas: ['Partido A', 'Partido B', 'Concordância', 'Votações em comum'],
                  linhas: fora.filter((d) => ordem.indexOf(d.partido_b) > ordem.indexOf(d.partido_a))
                    .map((d) => [d.partido_a, d.partido_b, fmt.pct(d.concordancia_pct), d.votacoes_comuns]) } });
});

await seguro(document.getElementById('tabela-partidos'), async () => {
  new Tabela(document.getElementById('tabela-partidos'), {
    linhas: partidos, nomeCsv: 'partidos',
    colunas: [
      { chave: 'sigla_partido', titulo: 'Partido', render: (p) => `<strong>${fmt.escapar(p.sigla_partido)}</strong>` },
      { chave: 'deputados', titulo: 'Deputados', num: true },
      { chave: 'participacao_pct', titulo: 'Participação', num: true, render: (p) => fmt.pct(p.participacao_pct) },
      { chave: 'fidelidade_pct', titulo: 'Fidelidade', num: true, render: (p) => fmt.pct(p.fidelidade_pct) },
      { chave: 'governismo_pct', titulo: 'Governismo', num: true, render: (p) => fmt.pct(p.governismo_pct) },
      { chave: 'autorias', titulo: 'Autorias', num: true },
      { chave: 'discursos', titulo: 'Discursos', num: true },
      { chave: 'gasto_por_deputado', titulo: 'Gasto por deputado', num: true, render: (p) => fmt.brl(p.gasto_por_deputado) },
    ],
  });
});
