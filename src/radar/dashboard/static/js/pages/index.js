// Visão Executiva: KPIs da semana, série diária, temas, Top 5 e pautas críticas.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, corTema, montar } from '../charts.js';
import { badgeImpacto, chipTema, kpi, vazio } from '../ui.js';
import * as fmt from '../format.js';

const m = await iniciar();
document.getElementById('acuracia-ia').textContent = m.ia?.acuracia_sem_vazamento ? fmt.pctFrac(m.ia.acuracia_sem_vazamento) : '—';
document.getElementById('custo-ia').textContent = m.ia ? `US$ ${fmt.num1(m.ia.custo_total_usd)}` : '—';

const soma = (ls, k) => ls.reduce((a, l) => a + (l[k] || 0), 0);

await seguro(document.querySelector('.kpi-row'), async () => {
  const k = await dados('kpis_diarios');
  const sem = k.slice(-7); const ant = k.slice(-14, -7); const ult30 = k.slice(-30);
  const def = [
    ['kpi-proposicoes', 'proposicoes'], ['kpi-relevantes', 'proposicoes_relevantes'],
    ['kpi-votacoes', 'votacoes'], ['kpi-eventos', 'eventos'], ['kpi-despesas', 'valor_despesas', fmt.brl],
  ];
  for (const [id, campo, formatter] of def) {
    kpi(document.getElementById(id), {
      valor: soma(sem, campo), anterior: soma(ant, campo), serie: ult30.map((d) => d[campo]), formatter: formatter || fmt.num,
    });
  }
  // agrega os dias em semanas (segunda a domingo); a semana leva a data da segunda-feira
  const segunda = (iso) => {
    const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  };
  const domingo = (iso) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 6); return d.toISOString().slice(0, 10); };
  const semanas = new Map();
  for (const d of k) {
    const s = semanas.get(segunda(d.data)) || { proposicoes: 0, votacoes: 0, dias: 0 };
    s.proposicoes += d.proposicoes; s.votacoes += d.votacoes; s.dias += 1;
    semanas.set(segunda(d.data), s);
  }
  const chaves = [...semanas.keys()].sort();
  const el = document.getElementById('graf-serie');
  el.classList.remove('skeleton');
  montar(el, (t) => ({
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0 },
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const s = chaves[ps[0].dataIndex]; const parcial = semanas.get(s).dias < 7 ? ' <i>(semana parcial)</i>' : '';
        return `Semana de ${fmt.data(s)} a ${fmt.data(domingo(s))}${parcial}<br>${ps.map((p) => `${p.marker} ${p.seriesName}: <b>${fmt.num(p.value)}</b>`).join('<br>')}`;
      },
    },
    xAxis: { type: 'category', data: chaves, axisLabel: { formatter: (v) => fmt.dataCurta(v), interval: 0, hideOverlap: true } },
    yAxis: { type: 'value', axisLabel: { formatter: fmt.num } },
    series: [
      { name: 'Proposições', type: 'line', smooth: true, symbolSize: 7, areaStyle: { opacity: 0.18 }, data: chaves.map((c) => semanas.get(c).proposicoes) },
      { name: 'Votações', type: 'line', smooth: true, symbolSize: 7, areaStyle: { opacity: 0.18 }, data: chaves.map((c) => semanas.get(c).votacoes) },
    ],
  }), { tabela: { colunas: ['Semana (segunda-feira)', 'Proposições', 'Votações'], linhas: chaves.map((c) => [fmt.data(c), semanas.get(c).proposicoes, semanas.get(c).votacoes]) } });
});

await seguro(document.getElementById('graf-temas'), async () => {
  const ts = await dados('proposicoes_tema_semana');
  const semanas = [...new Set(ts.map((d) => d.inicio_semana))].sort().slice(-4);
  const porTema = {};
  for (const d of ts) if (semanas.includes(d.inicio_semana)) porTema[d.tema] = (porTema[d.tema] || 0) + d.qtd;
  const ordem = Object.entries(porTema).sort((a, b) => b[1] - a[1]);
  const el = document.getElementById('graf-temas');
  el.classList.remove('skeleton');
  if (!ordem.length) { el.innerHTML = vazio(); return; }
  montar(el, barras({
    categorias: ordem.map(([t]) => t), horizontal: true, rotulo: true,
    series: [{ name: 'Proposições', data: ordem.map(([t, v]) => ({ value: v, itemStyle: { color: corTema(t) } })) }],
  }), { tabela: { colunas: ['Tema', 'Proposições'], linhas: ordem } });
});

await seguro(document.getElementById('lista-top'), async () => {
  const top = await dados('top_relevantes');
  const el = document.getElementById('lista-top');
  el.innerHTML = top.length ? top.map((p) => `
    <article class="item">
      <div class="item__head"><span class="item__title">${fmt.escapar(fmt.proposicao(p))}</span>${chipTema(p.tema_ia)}${badgeImpacto(p.nivel_impacto)}</div>
      <p class="item__text">${fmt.escapar(p.resumo_executivo)}</p>
      <div class="item__foot"><span>Relevância ${fmt.num1(p.relevancia_score * 100)}</span><span>Apresentada em ${fmt.data(p.data_apresentacao)}</span>
        <a href="${fmt.escapar(p.link_camara)}" rel="noopener" target="_blank">Ver na Câmara<span class="sr-only"> (abre em nova aba)</span></a></div>
    </article>`).join('') : vazio('Nenhuma proposição relevante nos últimos 7 dias.');
});

await seguro(document.getElementById('lista-pauta'), async () => {
  const pauta = await dados('pauta_critica');
  const el = document.getElementById('lista-pauta');
  el.innerHTML = pauta.length ? pauta.slice(0, 8).map((p) => `
    <article class="item">
      <div class="item__head"><span class="item__title">${fmt.escapar(p.proposicao)}</span>${chipTema(p.tema)}</div>
      <p class="item__text">${fmt.escapar(p.resumo || '')}</p>
      <div class="item__foot"><span>${fmt.data(p.data)} · ${fmt.escapar(p.orgao || '')}</span>
        <a href="${fmt.escapar(p.link_camara)}" rel="noopener" target="_blank">Ver na Câmara<span class="sr-only"> (abre em nova aba)</span></a></div>
    </article>`).join('') : vazio('Nenhum item de tema crítico na pauta dos próximos 7 dias.');
});
