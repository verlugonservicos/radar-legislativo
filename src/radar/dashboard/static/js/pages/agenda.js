// Agenda e Órgãos: calendário de eventos, órgãos, tipos/presença, pauta crítica e tabela.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, montar } from '../charts.js';
import { chipTema, Tabela, vazio } from '../ui.js';
import * as fmt from '../format.js';

await iniciar();
const ag = await dados('agenda');
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };
const contar = (ls, f) => { const m = new Map(); for (const d of ls) m.set(f(d), (m.get(f(d)) || 0) + 1); return [...m.entries()].sort((a, b) => b[1] - a[1]); };

await seguro(document.getElementById('graf-calendario'), async () => {
  const porDia = contar(ag, (d) => d.data);
  const datas = ag.map((d) => d.data).sort();
  if (!datas.length) { limpa('graf-calendario').innerHTML = vazio(); return; }
  montar(limpa('graf-calendario'), (t) => ({
    tooltip: { formatter: (p) => `${fmt.data(p.data[0])}: <b>${fmt.num(p.data[1])}</b> eventos` },
    visualMap: { min: 0, max: Math.max(...porDia.map((d) => d[1])), show: false, inRange: { color: [t.grid, t.accent] } },
    calendar: {
      range: [datas[0], datas[datas.length - 1]], cellSize: ['auto', 18], top: 30, left: 40, right: 16, bottom: 8,
      orient: 'horizontal', splitLine: { show: false }, itemStyle: { borderColor: t.surface, borderWidth: 3, color: t.grid },
      dayLabel: { firstDay: 1, nameMap: ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'], color: t.muted }, monthLabel: { nameMap: ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'], color: t.muted },
      yearLabel: { show: false },
    },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: porDia }],
  }), { tabela: { colunas: ['Data', 'Eventos'], linhas: porDia.map(([d, n]) => [fmt.data(d), n]) } });
});

await seguro(document.getElementById('graf-orgaos'), async () => {
  const o = contar(ag.filter((d) => d.orgao), (d) => d.orgao).slice(0, 15);
  montar(limpa('graf-orgaos'), barras({ categorias: o.map((d) => d[0]), horizontal: true, rotulo: true, series: [{ name: 'Eventos', data: o.map((d) => d[1]) }] }));
});

await seguro(document.getElementById('graf-tipos'), async () => {
  const tipos = contar(ag, (d) => d.tipo || 'Outro').slice(0, 10);
  const presenca = tipos.map(([t]) => { const ls = ag.filter((d) => (d.tipo || 'Outro') === t); return Math.round(ls.reduce((a, d) => a + d.presentes, 0) / ls.length); });
  montar(limpa('graf-tipos'), barras({
    categorias: tipos.map((d) => d[0]), horizontal: true,
    series: [{ name: 'Eventos', data: tipos.map((d) => d[1]) }, { name: 'Presença média', data: presenca }],
  }), { tabela: { colunas: ['Tipo', 'Eventos', 'Presença média'], linhas: tipos.map((d, i) => [d[0], d[1], presenca[i]]) } });
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
