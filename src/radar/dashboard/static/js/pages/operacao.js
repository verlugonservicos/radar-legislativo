// Operação e Qualidade: execuções, banco, cobertura, funil, rejeições e custos de IA.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, montar, rosca } from '../charts.js';
import { badgeStatus, Tabela } from '../ui.js';
import * as fmt from '../format.js';

const m = await iniciar();
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };
const ops = await dados('operacao');

await seguro(document.getElementById('graf-execucoes'), async () => {
  montar(limpa('graf-execucoes'), (t) => barras({
    categorias: ops.map((e) => `#${e.id_execucao}`), formatter: (v) => `${fmt.num(Math.round(v / 60))} min`,
    series: [{ name: 'Duração', data: ops.map((e) => ({ value: e.duracao_s, itemStyle: { color: { success: t.positive, partial: t.warning, failed: t.negative }[e.status] || t.muted } })) }],
  })(t), { tabela: { colunas: ['Execução', 'Modo', 'Status', 'Duração (min)'], linhas: ops.map((e) => [e.id_execucao, e.modo, e.status, Math.round(e.duracao_s / 60)]) } });
});

await seguro(document.getElementById('graf-banco'), async () => {
  const tam = await dados('tamanho_schemas');
  montar(limpa('graf-banco'), rosca({ itens: tam.map((s) => ({ name: s.schema, value: s.tamanho_mb })), formatter: (v) => `${fmt.num1(v)} MB` }),
    { tabela: { colunas: ['Schema', 'Tabelas', 'MB'], linhas: tam.map((s) => [s.schema, s.tabelas, fmt.num1(s.tamanho_mb)]) } });
});

await seguro(document.getElementById('grade-cobertura'), async () => {
  const cob = await dados('cobertura');
  const grupos = [...new Set(cob.map((c) => c.grupo))];
  const classe = (s) => (s === 'ok' ? '' : s === 'erro' || s === 'falha' ? 'is-err' : 'is-warn');
  document.getElementById('grade-cobertura').innerHTML = `<p style="margin-top:0"><strong>${m.cobertura}</strong> endpoints com status ok</p>${grupos.map((g) => `
    <div style="margin-bottom:var(--space-3)"><div class="muted" style="font-size:var(--fs-xs);margin-bottom:4px">${fmt.escapar(g)}</div>
    <div class="coverage" role="list">${cob.filter((c) => c.grupo === g).map((c) => `<span role="listitem" class="${classe(c.status)}" title="${fmt.escapar(c.endpoint)}: ${fmt.escapar(c.status)} · ${fmt.num(c.linhas_bronze)} linhas na Bronze" aria-label="${fmt.escapar(c.endpoint)}: ${fmt.escapar(c.status)}"></span>`).join('')}</div></div>`).join('')}`;
});

await seguro(document.getElementById('graf-funil'), async () => {
  const f = await dados('funil_camadas');
  montar(limpa('graf-funil'), barras({
    categorias: f.map((d) => d.entidade),
    series: [{ name: 'Bronze', data: f.map((d) => d.bronze) }, { name: 'Silver', data: f.map((d) => d.silver) }, { name: 'Gold', data: f.map((d) => d.gold) }],
  }), { tabela: { colunas: ['Entidade', 'Bronze', 'Silver', 'Gold', 'Rejeitados'], linhas: f.map((d) => [d.entidade, d.bronze, d.silver, d.gold, d.rejeitados]) } });
});

await seguro(document.getElementById('graf-qualidade'), async () => {
  const q = await dados('qualidade');
  const regras = new Map();
  for (const d of q) { const k = `${d.entidade} · ${d.regra}`; regras.set(k, (regras.get(k) || 0) + d.qtd); }
  const ls = [...regras.entries()].sort((a, b) => b[1] - a[1]);
  montar(limpa('graf-qualidade'), barras({ categorias: ls.map((d) => d[0]), horizontal: true, rotulo: true, series: [{ name: 'Registros', data: ls.map((d) => d[1]) }] }));
});

await seguro(document.getElementById('graf-custos'), async () => {
  const c = await dados('custos_ia');
  const porOp = new Map();
  for (const d of c) porOp.set(d.operacao, (porOp.get(d.operacao) || 0) + d.custo_usd);
  const ls = [...porOp.entries()].sort((a, b) => b[1] - a[1]);
  const usd = (v) => `US$ ${v.toFixed(v < 0.01 ? 4 : 2).replace('.', ',')}`;
  montar(limpa('graf-custos'), barras({ categorias: ls.map((d) => d[0]), horizontal: true, rotulo: true, formatter: usd, series: [{ name: 'Custo', data: ls.map((d) => d[1]) }] }));
  const itens = c.filter((d) => d.operacao === 'resumo').reduce((a, d) => a + d.itens, 0);
  document.getElementById('kv-custos').innerHTML = `<dt>Total</dt><dd><strong>${usd(m.ia?.custo_total_usd || 0)}</strong></dd>
    <dt>Resumos gerados</dt><dd>${fmt.num(itens)}</dd><dt>Modelos</dt><dd>${fmt.escapar([...new Set(c.map((d) => d.modelo))].join(', '))}</dd>`;
});

await seguro(document.getElementById('tabela-execucoes'), async () => {
  new Tabela(document.getElementById('tabela-execucoes'), {
    linhas: [...ops].reverse(), nomeCsv: 'execucoes',
    colunas: [
      { chave: 'id_execucao', titulo: 'Execução', num: true },
      { chave: 'modo', titulo: 'Modo' },
      { chave: 'status', titulo: 'Status', render: (e) => badgeStatus(e.status) },
      { chave: 'iniciado_em', titulo: 'Início', render: (e) => fmt.dataHora(e.iniciado_em) },
      { chave: 'duracao_s', titulo: 'Duração', num: true, render: (e) => `${fmt.num(Math.round(e.duracao_s / 60))} min` },
      { chave: 'endpoints', titulo: 'Endpoints', num: true },
      { chave: 'custo_ia_usd', titulo: 'Custo IA', num: true, render: (e) => (e.custo_ia_usd ? `US$ ${e.custo_ia_usd.toFixed(4).replace('.', ',')}` : '—') },
      { chave: 'erro', titulo: 'Observação', clip: true, render: (e) => fmt.escapar(e.erro || '') },
    ],
  });
});
