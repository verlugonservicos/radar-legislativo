// Agenda e Órgãos: calendário de eventos, órgãos, tipos/presença, pauta crítica e tabela.
import { iniciar, seguro } from '../app.3b9094f3e7.js';
import { dados } from '../data.4fb3031e8e.js';
import { barras, linhaMedia, mediaDe, montar, PALETA } from '../charts.5bb8fe5a75.js';
import { chipTema, Tabela, vazio } from '../ui.6a7de658b0.js';
import * as fmt from '../format.20a0ca273f.js';

const m = await iniciar();
const ag = await dados('agenda');
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };
const contar = (ls, f) => { const m = new Map(); for (const d of ls) m.set(f(d), (m.get(f(d)) || 0) + 1); return [...m.entries()].sort((a, b) => b[1] - a[1]); };

await seguro(document.getElementById('graf-calendario'), async () => {
  const porDia = contar(ag, (d) => d.data);
  if (!porDia.length) { limpa('graf-calendario').innerHTML = vazio(); return; }
  // janela inteira (30 dias antes a 7 depois da data de referência), mesmo sem evento nas pontas: os dias
  // futuros aparecem vazios até a carga diária trazer a agenda; número de eventos dentro de cada dia
  const DIA = 86_400_000;
  const ref = Date.parse(`${(m.periodo?.fim || porDia.map((d) => d[0]).sort().at(-1)).slice(0, 10)}T00:00:00Z`);
  const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
  const max = Math.max(...porDia.map((d) => d[1]));
  montar(limpa('graf-calendario'), (t) => ({
    tooltip: { formatter: (p) => `${fmt.data(p.data[0])}: <b>${fmt.num(p.data[1])}</b> ${p.data[1] === 1 ? 'evento' : 'eventos'}` },
    visualMap: { min: 0, max, show: true, calculable: false, orient: 'horizontal', right: 16, top: 0, itemWidth: 10, itemHeight: 90,
      text: ['mais', 'menos'], textGap: 6, textStyle: { color: t.muted, fontSize: 11 }, inRange: { color: [t.grid, t.accent] } },
    calendar: {
      range: [iso(ref - 30 * DIA), iso(ref + 7 * DIA)], cellSize: ['auto', 30], top: 44, left: 40, right: 16, bottom: 8,
      orient: 'horizontal', splitLine: { show: false }, itemStyle: { borderColor: t.surface, borderWidth: 3, color: t.grid },
      dayLabel: { firstDay: 1, nameMap: ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'], color: t.muted }, monthLabel: { nameMap: ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'], color: t.muted },
      yearLabel: { show: false },
    },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: porDia.map(([d, n]) => ({ value: [d, n],
      // número no dia: claro sobre as células escuras, escuro sobre as claras
      label: { show: true, formatter: (p) => fmt.num(p.data.value[1]), fontSize: 12, fontWeight: 600,
               color: n > max * 0.55 ? t.surface : t.text } })) }],
  }), { tabela: { colunas: ['Data', 'Eventos'], linhas: porDia.map(([d, n]) => [fmt.data(d), n]) } });
});

await seguro(document.getElementById('graf-orgaos'), async () => {
  const comOrgao = ag.filter((d) => d.orgao);
  const todosOrgaos = contar(comOrgao, (d) => d.orgao);
  const o = todosOrgaos.slice(0, 15);
  // % do total de eventos com órgão no período (não só dos 15), com 2 casas
  const pct = (v) => fmt.pct2(comOrgao.length ? (100 * v) / comOrgao.length : 0);
  montar(limpa('graf-orgaos'), (t) => {
    const op = barras({ gradiente: 'invertido', categorias: o.map((d) => d[0]), horizontal: true, rotulo: true, series: [{ name: 'Eventos', data: o.map((d) => d[1]) }] })(t);
    op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.num(x.value)} (${pct(x.value)})` };
    op.grid = { ...op.grid, right: 104 };
    linhaMedia(op, mediaDe(todosOrgaos.map((d) => d[1])), t, { formatter: fmt.num1 });  // média de todos os órgãos
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => `<b>${fmt.escapar(ps[0].name)}</b><br>Eventos: <b>${fmt.num(ps[0].value)}</b> (${pct(ps[0].value)} do total de ${fmt.num(comOrgao.length)})` };
    return op;
  }, { tabela: { colunas: ['Órgão', 'Eventos', '% do total'], linhas: o.map(([n, v]) => [n, v, pct(v)]) } });
});

await seguro(document.getElementById('graf-tipos'), async () => {
  const todosTipos = contar(ag, (d) => d.tipo || 'Outro');
  const tipos = todosTipos.slice(0, 10);
  const presenca = tipos.map(([t]) => { const ls = ag.filter((d) => (d.tipo || 'Outro') === t); return Math.round(ls.reduce((a, d) => a + d.presentes, 0) / ls.length); });
  // duas médias, uma por série, na cor da série: eventos por tipo (todos os tipos) e presença média de
  // todos os eventos. Rótulos deitados: o dos eventos no topo (abaixo da legenda) e o da presença
  // embaixo, depois dos números do eixo, para um não encavalar no outro
  montar(limpa('graf-tipos'), (t) => {
    const op = barras({
      categorias: tipos.map((d) => d[0]), horizontal: true,
      series: [{ name: 'Eventos', data: tipos.map((d) => d[1]) }, { name: 'Presença média', data: presenca }],
    })(t);
    const cores = [t.accent, PALETA[1]];  // as cores do tema para as duas séries
    linhaMedia(op, mediaDe(todosTipos.map((d) => d[1])), t, { formatter: fmt.num1, rotulo: 'média eventos', cor: cores[0] });
    linhaMedia(op, mediaDe(ag.map((d) => d.presentes)), t,
      { formatter: fmt.num1, rotulo: 'presença média', serie: 1, cor: cores[1], posicao: 'end', distancia: 24 });
    op.grid = { ...op.grid, top: 52, bottom: 30 };  // espaço para os dois rótulos
    return op;
  }, { tabela: { colunas: ['Tipo', 'Eventos', 'Presença média'], linhas: tipos.map((d, i) => [d[0], d[1], presenca[i]]) } });
});

await seguro(document.getElementById('lista-pauta'), async () => {
  const p = await dados('pauta_critica');
  document.getElementById('lista-pauta').innerHTML = p.length ? p.map((i) => `<article class="item"><div class="item__head">
    <span class="item__title">${fmt.escapar(i.proposicao)}</span>${chipTema(i.tema)}<span class="muted">${fmt.data(i.data)} · ${fmt.escapar(i.orgao || '')}</span></div>
    <p class="item__text">${fmt.escapar(i.resumo || '')}</p></article>`).join('') : vazio('Nenhum item de tema crítico na pauta dos próximos 7 dias.');
});

await seguro(document.getElementById('tabela-agenda'), async () => {
  new Tabela(document.getElementById('tabela-agenda'), {
    linhas: [...ag].sort((a, b) => (b.data + b.hora).localeCompare(a.data + a.hora)), nomeCsv: 'agenda',
    colunas: [
      { chave: 'data', titulo: 'Data', render: (d) => `${fmt.data(d.data)} <span class="muted">${fmt.escapar(d.hora || '')}</span>` },
      { chave: 'orgao', titulo: 'Órgão', render: (d) => `<span title="${fmt.escapar(d.orgao_nome || '')}">${fmt.escapar(d.orgao || '—')}</span>` },
      { chave: 'tipo', titulo: 'Tipo' },
      { chave: 'descricao', titulo: 'Descrição', clip: true },
      { chave: 'situacao', titulo: 'Situação' },
      { chave: 'itens_pauta', titulo: 'Itens', num: true },
      { chave: 'itens_criticos', titulo: 'Críticos', num: true, render: (d) => (d.itens_criticos ? `<span class="badge badge--alto">${d.itens_criticos}</span>` : '0') },
      { chave: 'presentes', titulo: 'Presentes', num: true },
    ],
  });
});
