// Operação e Qualidade: execuções, banco, cobertura, funil, rejeições e custos de IA.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, montar, rosca } from '../charts.js';
import { badgeStatus, Tabela } from '../ui.js';
import * as fmt from '../format.js';

const m = await iniciar();
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };
const ops = await dados('operacao');
// cores das camadas do medalhão, próximas dos metais (bronze, prata, ouro); ops em grafite neutro
const COR_CAMADA = { bronze: '#B87333', silver: '#A8A9AD', gold: '#F2C200', ops: '#475569' };

await seguro(document.getElementById('graf-execucoes'), async () => {
  // rótulo no topo de cada barra (duração em minutos); eixo em minutos "redondos" (antes: 83, 167, 250…)
  const min = (s) => `${fmt.num(Math.round(s / 60))} min`;
  const maiorMin = Math.max(...ops.map((e) => e.duracao_s / 60), 1);
  const passo = [10, 20, 30, 60, 120].find((p) => maiorMin / p <= 5) || 120;
  montar(limpa('graf-execucoes'), (t) => {
    const op = barras({
      categorias: ops.map((e) => `#${e.id_execucao}`), formatter: min, rotulo: true,
      series: [{ name: 'Duração', data: ops.map((e) => ({ value: e.duracao_s, itemStyle: { color: { success: t.positive, partial: t.warning, failed: t.negative }[e.status] || t.muted } })) }],
    })(t);
    op.yAxis = { ...op.yAxis, interval: passo * 60, max: Math.ceil(maiorMin / passo) * passo * 60 };
    return op;
  }, { tabela: { colunas: ['Execução', 'Modo', 'Status', 'Duração (min)'], linhas: ops.map((e) => [e.id_execucao, e.modo, e.status, Math.round(e.duracao_s / 60)]) } });
});

await seguro(document.getElementById('graf-banco'), async () => {
  const tam = await dados('tamanho_schemas');
  // rótulos ao lado da rosca: camada, tamanho e % do banco, com linha-guia
  const totalMb = tam.reduce((a, s) => a + s.tamanho_mb, 0);
  const pcts = fmt.pctsExatos(tam.map((s) => s.tamanho_mb));
  montar(limpa('graf-banco'), (t) => {
    const op = rosca({ itens: tam.map((s) => ({ name: s.schema, value: s.tamanho_mb, itemStyle: COR_CAMADA[s.schema] ? { color: COR_CAMADA[s.schema] } : undefined })),
                       formatter: (v) => `${fmt.num1(v)} MB` })(t);
    op.series[0].label = { show: true, position: 'outside', alignTo: 'edge', edgeDistance: 6, overflow: 'none', color: t.text, fontSize: 12, lineHeight: 16,
      formatter: (p) => `{n|${p.name}}\n{v|${fmt.num1(p.value)} MB · ${pcts[p.dataIndex]}}`,
      rich: { n: { fontWeight: 700, color: t.text, fontSize: 12 }, v: { color: t.muted, fontSize: 11 } } };
    op.series[0].labelLine = { show: true, length: 12, length2: 10, lineStyle: { color: t.muted } };
    op.series[0].radius = ['40%', '60%'];
    op.series[0].avoidLabelOverlap = true;
    op.title = { text: `${fmt.num1(totalMb)} MB`, subtext: 'total', left: 'center', top: '38%',
      textStyle: { fontSize: 16, fontWeight: 700, color: t.text }, subtextStyle: { color: t.muted, fontSize: 11 } };
    return op;
  },
    { tabela: { colunas: ['Schema', 'Tabelas', 'MB'], linhas: tam.map((s) => [s.schema, s.tabelas, fmt.num1(s.tamanho_mb)]) } });
});

await seguro(document.getElementById('grade-cobertura'), async () => {
  const cob = await dados('cobertura');
  const grupos = [...new Set(cob.map((c) => c.grupo))];
  const classe = (s) => (s === 'ok' ? '' : s === 'erro' || s === 'falha' ? 'is-err' : 'is-warn');
  // grupos em 2 colunas (o grupo grande, "referencias", ocupa a linha toda), com "ok/total" ao lado do nome
  const grupo = (g) => {
    const cs = cob.filter((c) => c.grupo === g); const ok = cs.filter((c) => c.status === 'ok').length;
    return `<div class="cobertura__grupo${cs.length > 12 ? ' cobertura__grupo--largo' : ''}">
      <div class="cobertura__nome"><span>${fmt.escapar(g)}</span><span class="muted">${ok}/${cs.length}</span></div>
      <div class="coverage" role="list">${cs.map((c) => `<span role="listitem" class="${classe(c.status)}" title="${fmt.escapar(c.endpoint)}: ${fmt.escapar(c.status)} · ${fmt.num(c.linhas_bronze)} linhas na Bronze" aria-label="${fmt.escapar(c.endpoint)}: ${fmt.escapar(c.status)}"></span>`).join('')}</div></div>`;
  };
  document.getElementById('grade-cobertura').innerHTML = `<p class="cobertura__total"><strong>${m.cobertura}</strong> endpoints com status ok</p>
    <div class="cobertura__grupos">${grupos.map(grupo).join('')}</div>`;
});

await seguro(document.getElementById('graf-funil'), async () => {
  const f = await dados('funil_camadas');
  montar(limpa('graf-funil'), barras({
    categorias: f.map((d) => d.entidade),
    series: [{ name: 'Bronze', data: f.map((d) => d.bronze), itemStyle: { color: COR_CAMADA.bronze } },
             { name: 'Silver', data: f.map((d) => d.silver), itemStyle: { color: COR_CAMADA.silver } },
             { name: 'Gold', data: f.map((d) => d.gold), itemStyle: { color: COR_CAMADA.gold } }],
  }), { tabela: { colunas: ['Entidade', 'Bronze', 'Silver', 'Gold', 'Rejeitados'], linhas: f.map((d) => [d.entidade, d.bronze, d.silver, d.gold, d.rejeitados]) } });
});

// barras horizontais com o % do total entre parênteses (2 casas), no padrão dos demais painéis
function comPercentual(id, ls, formatter, nome, sufixo) {
  const pcts = fmt.pctsExatos(ls.map((d) => d[1]));  // conjunto completo: fecha 100,00%
  montar(limpa(id), (t) => {
    const op = barras({ gradiente: true, categorias: ls.map((d) => d[0]), horizontal: true, rotulo: true, formatter, series: [{ name: nome, data: ls.map((d) => d[1]) }] })(t);
    op.series[0].label = { ...op.series[0].label, formatter: (x) => `${formatter(x.value)} (${pcts[x.dataIndex]})` };
    op.grid = { ...op.grid, right: 120 };
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps) => `<b>${fmt.escapar(ps[0].name)}</b><br>${nome}: <b>${formatter(ps[0].value)}</b> (${pcts[ps[0].dataIndex]} ${sufixo})` };
    return op;
  }, { tabela: { colunas: ['Item', nome, '% do total'], linhas: ls.map(([n, v], i) => [n, formatter(v), pcts[i]]) } });
}

await seguro(document.getElementById('graf-qualidade'), async () => {
  const q = await dados('qualidade');
  const regras = new Map();
  for (const d of q) { const k = `${d.entidade} · ${d.regra}`; regras.set(k, (regras.get(k) || 0) + d.qtd); }
  const ls = [...regras.entries()].sort((a, b) => b[1] - a[1]);
  comPercentual('graf-qualidade', ls, fmt.num, 'Registros', 'das rejeições');
});

await seguro(document.getElementById('graf-custos'), async () => {
  const c = await dados('custos_ia');
  const porOp = new Map();
  for (const d of c) porOp.set(d.operacao, (porOp.get(d.operacao) || 0) + d.custo_usd);
  const ls = [...porOp.entries()].sort((a, b) => b[1] - a[1]);
  const usd = (v) => `US$ ${v.toFixed(v < 0.01 ? 4 : 2).replace('.', ',')}`;
  comPercentual('graf-custos', ls, usd, 'Custo', 'do custo total');
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
