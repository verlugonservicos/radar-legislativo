// Despesas da Cota: série mensal, tipos, fornecedores, partido, UF, outliers e quarentena.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, montar } from '../charts.js';
import { Tabela } from '../ui.js';
import * as fmt from '../format.js';

await iniciar();
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

await seguro(document.getElementById('graf-mensal'), async () => {
  const meses = (await dados('despesas_mensal')).map((d) => [`${d.ano}-${String(d.mes).padStart(2, '0')}`, d.valor_liquido]);
  montar(limpa('graf-mensal'), barras({
    categorias: meses.map(([k]) => `${MESES[Number(k.slice(5)) - 1]}/${k.slice(2, 4)}`), formatter: fmt.brl, rotulo: true,
    gradiente: true,
    series: [{
      name: 'Valor líquido', data: meses.map(([, v]) => Math.round(v)),
      // média dos meses carregados: referência para ver quais meses ficaram acima ou abaixo
      markLine: { silent: true, symbol: 'none', data: [{ type: 'average', name: 'Média' }],
        lineStyle: { type: 'dashed', width: 1.5, color: '#64748B' },
        label: { position: 'insideEndTop', formatter: (p) => `Média: ${fmt.brl(p.value)}`, color: '#64748B', fontWeight: 600 } },
    }],
  }), { tabela: { colunas: ['Mês', 'Valor líquido'], linhas: meses.map(([k, v]) => [k, fmt.brlCheio(v)]) } });
});

await seguro(document.getElementById('kv-quarentena'), async () => {
  const q = (await dados('qualidade')).filter((d) => d.entidade === 'despesas');
  const qtd = q.reduce((a, d) => a + d.qtd, 0); const valor = q.reduce((a, d) => a + (d.valor || 0), 0);
  document.getElementById('kv-quarentena').innerHTML = `<dt>Lançamentos</dt><dd><strong>${fmt.num(qtd)}</strong></dd>
    <dt>Valor dos documentos</dt><dd><strong>${fmt.brlCheio(valor)}</strong></dd><dt>Regra</dt><dd>valor do documento ≥ 0</dd>`;
});

// % do total da cota no período (todos os tipos), com 2 casas, entre parênteses ao lado de cada barra
const todosTipos = await dados('despesas_tipo');
const totalCota = todosTipos.reduce((t, d) => t + (d.valor_liquido || 0), 0);
const pctCota = (v) => fmt.pct2(totalCota ? (100 * v) / totalCota : 0);
const comPct = (op) => {
  op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.brl(x.value)} (${pctCota(x.value)})` };
  op.grid = { ...op.grid, right: 132 };
  return op;
};

await seguro(document.getElementById('graf-tipos'), async () => {
  const tipos = todosTipos.slice(0, 12).map((d) => [d.tipo_despesa, d.valor_liquido]);
  montar(limpa('graf-tipos'), (t) => {
    const op = comPct(barras({
      gradiente: true, categorias: tipos.map(([tp]) => (tp.length > 38 ? `${tp.slice(0, 36)}…` : tp)), horizontal: true, formatter: fmt.brl, rotulo: true,
      series: [{ name: 'Valor líquido', data: tipos.map(([, v]) => Math.round(v)) }],
    })(t));
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => `<b>${fmt.escapar(tipos[ps[0].dataIndex][0])}</b><br>${fmt.brlCheio(ps[0].value)} (${pctCota(ps[0].value)} do total da cota)` };
    return op;
  }, { tabela: { colunas: ['Tipo', 'Valor líquido', '% do total'], linhas: tipos.map(([tp, v]) => [tp, fmt.brlCheio(v), pctCota(v)]) } });
});

await seguro(document.getElementById('graf-fornecedores'), async () => {
  const f = (await dados('fornecedores')).slice(0, 15);
  montar(limpa('graf-fornecedores'), (t) => {
    const op = comPct(barras({
      gradiente: true, categorias: f.map((d) => (d.nome.length > 32 ? `${d.nome.slice(0, 30)}…` : d.nome)), horizontal: true, formatter: fmt.brl, rotulo: true,
      series: [{ name: 'Valor líquido', data: f.map((d) => d.valor) }],
    })(t));
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => `<b>${fmt.escapar(f[ps[0].dataIndex].nome)}</b><br>${fmt.brlCheio(ps[0].value)} (${pctCota(ps[0].value)} do total da cota)` };
    return op;
  }, { tabela: { colunas: ['Fornecedor', 'Valor', '% do total', 'Notas', 'Deputados'], linhas: f.map((d) => [d.nome, fmt.brlCheio(d.valor), pctCota(d.valor), d.qtd, d.deputados]) } });
});

await seguro(document.getElementById('graf-partido'), async () => {
  const todos = await dados('partidos');
  const ps = todos.filter((p) => p.deputados >= 3).sort((a, b) => b.gasto_por_deputado - a.gasto_por_deputado);
  const dep = Object.fromEntries(ps.map((p) => [p.sigla_partido, p.deputados]));
  // % = fatia do partido no gasto total da cota (todos os partidos), como no gráfico por UF
  const total = todos.reduce((s, p) => s + (p.gasto_total || 0), 0);
  const pct = (p) => fmt.pct2(total ? (100 * (p.gasto_total || 0)) / total : 0);
  montar(limpa('graf-partido'), (t) => {
    const op = barras({
      gradiente: true, categorias: ps.map((p) => p.sigla_partido), horizontal: true, formatter: fmt.brl, rotulo: true,
      series: [{ name: 'Gasto por deputado', data: ps.map((p) => p.gasto_por_deputado) }],
    })(t);
    op.yAxis.axisLabel = { ...op.yAxis.axisLabel, formatter: (s) => `${s} (${fmt.num(dep[s])})` };  // nº de deputados
    op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.brl(x.value)} (${pct(ps[x.dataIndex])})` };
    op.grid = { ...op.grid, right: 132 };
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (xs) => {
      const p = ps[xs[0].dataIndex];
      return `<b>${fmt.escapar(p.sigla_partido)}</b> · ${fmt.num(p.deputados)} deputados<br>Por deputado: <b>${fmt.brl(p.gasto_por_deputado)}</b>`
        + `<br>Gasto total: ${fmt.brlCheio(p.gasto_total)} (${pct(p)} do total da cota)`;
    } };
    return op;
  }, { tabela: { colunas: ['Partido', 'Deputados', 'Gasto por deputado', 'Gasto total', '% do total'],
                 linhas: ps.map((p) => [p.sigla_partido, p.deputados, fmt.brl(p.gasto_por_deputado), fmt.brlCheio(p.gasto_total), pct(p)]) } });
});

await seguro(document.getElementById('graf-uf'), async () => {
  // barras horizontais (como o gráfico por partido), com o nº de deputados ao lado da UF; o % é a fatia
  // da UF no gasto total da cota (a média por deputado não soma 100%, o gasto total soma)
  const us = (await dados('deputados_uf')).sort((a, b) => b.gasto_por_deputado - a.gasto_por_deputado);
  const pctsUf = fmt.pctsExatos(us.map((u) => u.gasto_total || 0));  // as 27 UFs: fecha 100,00%
  const pct = (u) => pctsUf[us.indexOf(u)];
  const porUf = Object.fromEntries(us.map((u) => [u.sigla_uf, u]));
  montar(limpa('graf-uf'), (t) => {
    const op = barras({
      gradiente: true, categorias: us.map((u) => u.sigla_uf), horizontal: true, rotulo: true, formatter: fmt.brl,
      series: [{ name: 'Gasto por deputado', data: us.map((u) => u.gasto_por_deputado) }],
    })(t);
    op.yAxis.axisLabel = { ...op.yAxis.axisLabel, formatter: (s) => `${s} (${fmt.num(porUf[s].deputados)})` };
    op.series[0].label = { ...op.series[0].label, formatter: (x) => `${fmt.brl(x.value)} (${pct(us[x.dataIndex])})` };
    op.grid = { ...op.grid, right: 132 };
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps) => {
      const u = us[ps[0].dataIndex];
      return `<b>${fmt.escapar(u.sigla_uf)}</b> · ${fmt.num(u.deputados)} deputados<br>Por deputado: <b>${fmt.brl(u.gasto_por_deputado)}</b>`
        + `<br>Gasto total: ${fmt.brlCheio(u.gasto_total)} (${pct(u)} do total da cota)`;
    } };
    return op;
  }, { tabela: { colunas: ['UF', 'Deputados', 'Gasto por deputado', 'Gasto total', '% do total'],
                 linhas: us.map((u) => [u.sigla_uf, u.deputados, fmt.brl(u.gasto_por_deputado), fmt.brlCheio(u.gasto_total), pct(u)]) } });
});

await seguro(document.getElementById('tabela-outliers'), async () => {
  new Tabela(document.getElementById('tabela-outliers'), {
    linhas: await dados('despesas_outliers'), nomeCsv: 'despesas_outliers',
    colunas: [
      { chave: 'nome', titulo: 'Deputado', render: (d) => `<strong>${fmt.escapar(d.nome)}</strong> <span class="muted">${fmt.escapar(d.sigla_partido)}-${fmt.escapar(d.sigla_uf)}</span>` },
      { chave: 'tipo_despesa', titulo: 'Tipo de despesa', clip: true },
      { chave: 'total', titulo: 'Total', num: true, render: (d) => fmt.brlCheio(d.total) },
      { chave: 'z_score', titulo: 'z-score', num: true, render: (d) => fmt.num1(d.z_score) },
    ],
  });
});
