// Visão Executiva: KPIs da semana, série diária, temas, Top 5 e pautas críticas.
import { iniciar, seguro } from '../app.3b9094f3e7.js';
import { dados } from '../data.2c348c9ca7.js';
import { barras, corTema, montar, linhaMedia, mediaDe } from '../charts.dd3790bfbe.js';
import { badgeImpacto, chipTema, kpi, vazio } from '../ui.6a7de658b0.js';
import * as fmt from '../format.20a0ca273f.js';

const m = await iniciar();
document.getElementById('acuracia-ia').textContent = m.ia?.acuracia_sem_vazamento ? fmt.pctFrac(m.ia.acuracia_sem_vazamento) : '—';
document.getElementById('custo-ia').textContent = m.ia ? `US$ ${fmt.num1(m.ia.custo_total_usd)}` : '—';

const soma = (ls, k) => ls.reduce((a, l) => a + (l[k] || 0), 0);

await seguro(document.querySelector('.kpi-row'), async () => {
  const k = await dados('kpis_diarios');
  const sem = k.slice(-7); const ant = k.slice(-14, -7); const ult30 = k.slice(-30);
  const def = [
    ['kpi-proposicoes', 'proposicoes'], ['kpi-relevantes', 'proposicoes_relevantes'],
    ['kpi-votacoes', 'votacoes'], ['kpi-eventos', 'eventos'],
  ];
  for (const [id, campo, formatter] of def) {
    kpi(document.getElementById(id), {
      valor: soma(sem, campo), anterior: soma(ant, campo), serie: ult30.map((d) => d[campo]), formatter: formatter || fmt.num,
    });
  }
  // Despesas da cota: por mês fechado, não 7 dias. A nota fiscal chega à Câmara com até ~90 dias de atraso,
  // então os últimos 7 dias (pela data do documento) davam quase zero. Usa o último mês completo antes do mês
  // de referência e compara com o anterior; o mini-gráfico mostra os meses.
  const mensal = await dados('despesas_mensal');
  const ref = m.periodo?.fim?.slice(0, 7) || new Date().toISOString().slice(0, 7);
  const chave = (d) => `${d.ano}-${String(d.mes).padStart(2, '0')}`;
  const fechados = mensal.filter((d) => chave(d) < ref);
  const ultimo = fechados.at(-1); const penultimo = fechados.at(-2);
  if (ultimo) {
    const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    const nome = (d) => `${MES[d.mes - 1]}/${String(d.ano).slice(2)}`;
    kpi(document.getElementById('kpi-despesas'), {
      valor: ultimo.valor_liquido, anterior: penultimo?.valor_liquido, serie: fechados.slice(-6).map((d) => d.valor_liquido),
      formatter: fmt.brl, comparacao: penultimo ? `vs. ${nome(penultimo)}` : '', rotuloSerie: 'Tendência mensal',
      dica: `Valor líquido · ${nome(ultimo)} (último mês fechado; notas chegam com até 90 dias de atraso)`,
    });
  }
  // agrega os dias em semanas (segunda a domingo); a semana leva a data da segunda-feira
  const segunda = (iso) => {
    const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  };
  const semanas = new Map();
  for (const d of k) {
    const s = semanas.get(segunda(d.data)) || { proposicoes: 0, votacoes: 0, dias: 0 };
    s.proposicoes += d.proposicoes; s.votacoes += d.votacoes; s.dias += 1;
    semanas.set(segunda(d.data), s);
  }
  const chaves = [...semanas.keys()].sort();
  const el = document.getElementById('graf-serie');
  el.classList.remove('skeleton');
  // média semanal de cada série (linha tracejada; semanas parciais entram no cálculo)
  const comMedias = (op, t) => {
    linhaMedia(op, mediaDe(chaves.map((c) => semanas.get(c).proposicoes)), t, { eixo: 'y', serie: 0, rotulo: 'média proposições', formatter: fmt.num });
    linhaMedia(op, mediaDe(chaves.map((c) => semanas.get(c).votacoes)), t, { eixo: 'y', serie: 1, rotulo: 'média votações', formatter: fmt.num });
    return op;
  };
  montar(el, (t) => comMedias({
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0 },
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const s = chaves[ps[0].dataIndex]; const parcial = semanas.get(s).dias < 7 ? ' <i>(semana parcial)</i>' : '';
        return `<b>${fmt.rotuloSemana(s)}</b>${parcial}<br>${ps.map((p) => `${p.marker} ${p.seriesName}: <b>${fmt.num(p.value)}</b>`).join('<br>')}`;
      },
    },
    xAxis: { type: 'category', data: chaves, axisLabel: { formatter: (v) => `S-${fmt.semanaAno(v)}`, interval: 0, hideOverlap: true } },  // nº da semana (ISO)
    yAxis: { type: 'value', axisLabel: { formatter: fmt.num } },
    series: [
      { name: 'Proposições', type: 'line', smooth: true, symbolSize: 7, areaStyle: { opacity: 0.18 }, data: chaves.map((c) => semanas.get(c).proposicoes) },
      { name: 'Votações', type: 'line', smooth: true, symbolSize: 7, areaStyle: { opacity: 0.18 }, data: chaves.map((c) => semanas.get(c).votacoes) },
    ],
  }, t), { tabela: { colunas: ['Semana', 'Início (segunda)', 'Proposições', 'Votações'], linhas: chaves.map((c) => [`S-${fmt.semanaAno(c)}`, fmt.data(c), semanas.get(c).proposicoes, semanas.get(c).votacoes]) } });
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
  // % do total das 4 semanas, com 2 casas, entre parênteses (mesmo padrão dos outros gráficos de barras)
  const pcts = fmt.pctsExatos(ordem.map(([, v]) => v));  // conjunto completo: fecha 100,00%
  montar(el, (t) => {
    const op = barras({
      categorias: ordem.map(([tm]) => tm), horizontal: true, rotulo: true,
      series: [{ name: 'Proposições', data: ordem.map(([tm, v]) => ({ value: v, itemStyle: { color: corTema(tm) } })) }],
    })(t);
    // fundo da cor do card atrás do número: a linha da média passa por baixo sem riscar o texto
    op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.num(x.value)} (${pcts[x.dataIndex]})`,
                           backgroundColor: t.surface, padding: [1, 3], borderRadius: 3 };
    op.grid = { ...op.grid, right: 104 };
    linhaMedia(op, mediaDe(ordem.map(([, v]) => v)), t, { formatter: fmt.num1 });  // média de proposições por tema
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => `<b>${fmt.escapar(ps[0].name)}</b><br>Proposições: <b>${fmt.num(ps[0].value)}</b> (${pcts[ps[0].dataIndex]} do total)` };
    return op;
  }, { tabela: { colunas: ['Tema', 'Proposições', '% do total'], linhas: ordem.map(([tm, v], i) => [tm, v, pcts[i]]) } });
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
