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

await seguro(document.getElementById('graf-dispersao'), async () => {
  const ps = partidos.filter((p) => p.fidelidade_pct !== null && p.governismo_pct !== null);
  const maxDep = Math.max(...ps.map((p) => p.deputados));
  montar(limpa('graf-dispersao'), (t) => ({
    grid: { left: 8, right: 24, top: 24, bottom: 8, containLabel: true },
    tooltip: { formatter: (p) => `<b>${fmt.escapar(p.data[3])}</b><br>Fidelidade ${fmt.pct(p.data[0])}<br>Governismo ${fmt.pct(p.data[1])}<br>${fmt.num(p.data[2])} deputados` },
    xAxis: { type: 'value', name: 'Fidelidade ao partido (%)', nameLocation: 'middle', nameGap: 28, min: (v) => Math.max(0, Math.floor(v.min / 10) * 10), max: 100, nameTextStyle: { color: t.muted } },
    yAxis: { type: 'value', name: 'Governismo (%)', min: 0, max: 100, nameTextStyle: { color: t.muted } },
    series: [{
      type: 'scatter', data: ps.map((p) => [p.fidelidade_pct, p.governismo_pct, p.deputados, p.sigla_partido]),
      symbolSize: (d) => 10 + 40 * Math.sqrt(d[2] / maxDep),
      itemStyle: { color: t.accent, opacity: 0.7, borderColor: t.surface, borderWidth: 1 },
      label: { show: true, formatter: (p) => p.data[3], position: 'top', fontSize: 10, color: t.muted },
      labelLayout: { hideOverlap: true },
    }],
  }), { tabela: { colunas: ['Partido', 'Deputados', 'Fidelidade', 'Governismo'], linhas: ps.map((p) => [p.sigla_partido, p.deputados, fmt.pct(p.fidelidade_pct), fmt.pct(p.governismo_pct)]) } });
});

await seguro(document.getElementById('graf-heatmap'), async () => {
  const sim = await dados('similaridade_partidos');
  const ordem = partidos.map((p) => p.sigla_partido).filter((s) => sim.some((d) => d.partido_a === s));
  const pontos = sim.filter((d) => ordem.includes(d.partido_a) && ordem.includes(d.partido_b))
    .map((d) => [ordem.indexOf(d.partido_a), ordem.indexOf(d.partido_b), d.concordancia_pct, d.votacoes_comuns]);
  montar(limpa('graf-heatmap'), (t) => ({
    grid: { left: 8, right: 8, top: 8, bottom: 56, containLabel: true },
    tooltip: { formatter: (p) => `${ordem[p.data[0]]} × ${ordem[p.data[1]]}: <b>${fmt.pct(p.data[2])}</b><br>${fmt.num(p.data[3])} votações em comum` },
    xAxis: { type: 'category', data: ordem, axisLabel: { rotate: 60, fontSize: 10 }, splitArea: { show: false } },
    yAxis: { type: 'category', data: ordem, axisLabel: { fontSize: 10 } },
    visualMap: { min: 0, max: 100, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 140,
      inRange: { color: [t.negative, t.surface, t.accent] }, textStyle: { color: t.muted }, formatter: (v) => `${Math.round(v)}%` },
    series: [{ type: 'heatmap', data: pontos, itemStyle: { borderColor: t.surface, borderWidth: 1 }, emphasis: { itemStyle: { borderColor: t.text } } }],
  }));
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
