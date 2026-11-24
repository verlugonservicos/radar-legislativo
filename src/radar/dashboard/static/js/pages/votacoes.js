// Votações e Partidos: votações por semana, participação, fidelidade × governismo e concordância.
/* global echarts */
import { iniciar, seguro } from '../app.js';
import { dados, meta } from '../data.js';
import { barras, GRADIENTE, montar } from '../charts.js';
import { Tabela } from '../ui.js';
import * as fmt from '../format.js';

await iniciar();
const partidos = await dados('partidos');
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };

// Votações por semana (segunda a domingo): a Câmara vota em 2 a 4 dias por semana e para no recesso e
// na campanha eleitoral; por dia, o eixo escondia esses intervalos. Semanas sem votação aparecem em zero.
await seguro(document.getElementById('graf-dia'), async () => {
  const [v, m] = await Promise.all([dados('votacoes_dia'), meta()]);
  const DIA = 86_400_000;
  const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
  const segunda = (s) => { const ms = Date.parse(`${s}T00:00:00Z`); return iso(ms - ((new Date(ms).getUTCDay() + 6) % 7) * DIA); };
  const fim = Date.parse(`${m.periodo.fim}T00:00:00Z`);
  const semanas = new Map();
  for (let ms = Date.parse(`${segunda(iso(fim - 89 * DIA))}T00:00:00Z`); ms <= fim; ms += 7 * DIA) {
    semanas.set(iso(ms), { aprovadas: 0, rejeitadas: 0, sem: 0, nominais: 0, dias: 0 });
  }
  for (const d of v) {
    const s = semanas.get(segunda(d.data));
    if (!s) continue;
    s.aprovadas += d.aprovadas; s.rejeitadas += d.rejeitadas; s.sem += d.total - d.aprovadas - d.rejeitadas;
    s.nominais += d.nominais; s.dias += 1;
  }
  const chaves = [...semanas.keys()];
  const total = (s) => s.aprovadas + s.rejeitadas + s.sem;
  montar(limpa('graf-dia'), (t) => {
    const op = barras({
      categorias: chaves.map((c) => fmt.dataCurta(c)), empilhado: true,
      series: [
        { name: 'Aprovadas', data: chaves.map((c) => semanas.get(c).aprovadas), itemStyle: { color: t.positive } },
        { name: 'Rejeitadas', data: chaves.map((c) => semanas.get(c).rejeitadas), itemStyle: { color: t.negative } },
        { name: 'Sem resultado', data: chaves.map((c) => semanas.get(c).sem), itemStyle: { color: t.grid } },
      ],
    })(t);
    op.tooltip.formatter = (ps) => {
      const s = semanas.get(chaves[ps[0].dataIndex]);
      const cab = `<b>Semana de ${fmt.data(chaves[ps[0].dataIndex])}</b><br>`;
      if (!total(s)) return `${cab}Sem votações`;
      return `${cab}${ps.map((p) => `${p.marker}${p.seriesName}: <b>${fmt.num(p.value)}</b>`).join('<br>')}`
        + `<br>Total: <b>${fmt.num(total(s))}</b> em ${s.dias} ${s.dias === 1 ? 'dia' : 'dias'} com votação`;
    };
    return op;
  }, { tabela: { colunas: ['Semana (segunda-feira)', 'Total', 'Aprovadas', 'Rejeitadas', 'Nominais', 'Dias com votação'],
                 linhas: chaves.map((c) => { const s = semanas.get(c); return [fmt.data(c), total(s), s.aprovadas, s.rejeitadas, s.nominais, s.dias]; }) } });
});

await seguro(document.getElementById('graf-participacao'), async () => {
  const ps = partidos.filter((p) => p.participacao_pct !== null).sort((a, b) => b.participacao_pct - a.participacao_pct);
  montar(limpa('graf-participacao'), barras({
    gradiente: 'invertido', categorias: ps.map((p) => p.sigla_partido), horizontal: true, rotulo: true, formatter: fmt.pct,
    series: [{ name: 'Participação', data: ps.map((p) => p.participacao_pct) }],
  }), { tabela: { colunas: ['Partido', 'Participação'], linhas: ps.map((p) => [p.sigla_partido, fmt.pct(p.participacao_pct)]) } });
});

const translucido = (hex, a) => (/^#[0-9a-f]{6}$/i.test(hex)
  ? `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})` : hex);

// grupos pela proximidade com o governo (só para colorir e facilitar a leitura)
const GRUPOS = [
  // cores neutras de propósito: verde/vermelho aqui soaria como julgamento político (governo = bom,
  // oposição = ruim); o degradê verde/vermelho fica para métricas de desempenho (gasto, participação)
  // faixas: ≥ 80% alinhados, 60–80% intermediários, < 60% distantes (o grafite segue o tema, para não
  // sumir no fundo escuro)
  { nome: 'Alinhados ao governo (≥ 80%)', teste: (g) => g >= 80, cor: () => '#0284C7' },
  { nome: 'Intermediários (60–80%)', teste: (g) => g >= 60 && g < 80, cor: () => '#F59E0B' },
  { nome: 'Distantes do governo (< 60%)', teste: (g) => g < 60, cor: (t) => t.muted },
];

await seguro(document.getElementById('graf-dispersao'), async () => {
  const ps = partidos.filter((p) => p.fidelidade_pct !== null && p.governismo_pct !== null);
  const maxDep = Math.max(...ps.map((p) => p.deputados));
  const minX = Math.max(0, Math.floor((Math.min(...ps.map((p) => p.fidelidade_pct)) - 3) / 20) * 20);  // eixo de 20 em 20
  const elDisp = limpa('graf-dispersao');
  const estreito = elDisp.clientWidth < 480;
  const TOPO = estreito ? 92 : 48;      // a legenda quebra em 3 linhas no celular

  // Posicionamento dos nomes sem sobreposição: prefere o lado esquerdo da bolha (à esquerda, depois
  // acima/abaixo à esquerda, em distâncias crescentes); só sem espaço tenta os outros lados. Fica com a
  // primeira posição que não encosta em outro nome nem em outra bolha; afastado, ganha linha-guia.
  const ocupados = [];
  let bolhas = [];
  const cruza = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  const cruzaCirculo = (r, c) => {
    const nx = Math.max(r.x, Math.min(c.x, r.x + r.w)); const ny = Math.max(r.y, Math.min(c.y, r.y + r.h));
    return (nx - c.x) ** 2 + (ny - c.y) ** 2 < (c.r + 2) ** 2;
  };
  const DIRECOES = [[-1, 0], [-1, -1], [-1, 1], [0, -1], [0, 1], [1, 0], [1, -1], [1, 1]];
  const DESLOCAMENTOS = [0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5];  // passos verticais (em alturas de rótulo) para o aglomerado
  function posicionarRotulo(p) {
    const inst = echarts.getInstanceByDom(elDisp);
    if (p.seriesIndex === 0 && p.dataIndex === 0) {  // começo de um novo desenho: recalcula o mapa de ocupação
      ocupados.length = 0;
      bolhas = ps.map((q) => {
        const [x, y] = inst.convertToPixel({ gridIndex: 0 }, [q.fidelidade_pct, q.governismo_pct]);
        return { x, y, r: (8 + 30 * Math.sqrt(q.deputados / maxDep)) / 2 };
      });
    }
    const largura = elDisp.clientWidth; const altura = elDisp.clientHeight;
    const cx = p.rect.x + p.rect.width / 2; const cy = p.rect.y + p.rect.height / 2; const raio = p.rect.width / 2;
    const lw = p.labelRect.width; const lh = p.labelRect.height;
    // ordem: lado esquerdo (perto → longe), depois esquerdo deslocado na vertical (aglomerado perto de
    // 100%), e só então os outros lados
    const tentativas = [];
    for (const d of [raio + 4, raio + 22, raio + 42]) for (const dir of DIRECOES.slice(0, 3)) tentativas.push([d, dir, 0]);
    for (const d of [raio + 22, raio + 42, raio + 70, raio + 100]) for (const k of DESLOCAMENTOS.slice(1)) tentativas.push([d, [-1, 0], k]);
    for (const d of [raio + 4, raio + 22, raio + 42]) for (const dir of DIRECOES.slice(3)) tentativas.push([d, dir, 0]);
    for (const [d, [ux, uy], k] of tentativas) {
      {
        const ax = cx + ux * d; const ay = cy + uy * d + k * (lh + 2);
        const r = { x: ux > 0 ? ax : ux < 0 ? ax - lw : ax - lw / 2, y: uy > 0 ? ay : uy < 0 ? ay - lh : ay - lh / 2, w: lw, h: lh };
        const dentro = r.x >= 40 && r.y >= TOPO - 6 && r.x + r.w <= largura - 4 && r.y + r.h <= altura - 24;
        if (dentro && !ocupados.some((o) => cruza(r, o)) && !bolhas.some((c) => cruzaCirculo(r, c))) {
          ocupados.push(r);
          return { x: r.x, y: r.y, align: 'left', verticalAlign: 'top' };
        }
      }
    }
    return { moveOverlap: 'shiftY' };  // sem posição livre: deixa o ECharts afastar na vertical
  }
  montar(elDisp, (t) => ({
    grid: { left: 20, right: 12, top: TOPO, bottom: 6, containLabel: true },
    legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, icon: 'circle' },
    tooltip: { formatter: (p) => `<b>${fmt.escapar(p.data[3])}</b> · ${fmt.num(p.data[2])} deputados<br>Fidelidade ao partido: ${fmt.pct(p.data[0])}<br>Governismo: ${fmt.pct(p.data[1])}` },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'inside', yAxisIndex: 0, filterMode: 'none' }],
    // sem título no eixo X (o subtítulo do card diz que o horizontal é a fidelidade): o gráfico usa o espaço
    xAxis: { type: 'value', min: minX, max: 101.5, interval: 20, axisLabel: { showMaxLabel: false, formatter: (v) => `${v}%` } },
    yAxis: { type: 'value', name: 'Governismo (%)', nameLocation: 'middle', nameRotate: 90, nameGap: 36, max: 102,
      min: Math.max(0, Math.floor((Math.min(...ps.map((p) => p.governismo_pct)) - 6) / 10) * 10),
      axisLabel: { showMaxLabel: false }, nameTextStyle: { color: t.muted } },
    series: GRUPOS.map((g, k) => ({
      type: 'scatter', name: g.nome,
      data: ps.filter((p) => g.teste(p.governismo_pct)).map((p) => [p.fidelidade_pct, p.governismo_pct, p.deputados, p.sigla_partido]),
      symbolSize: (d) => 8 + 30 * Math.sqrt(d[2] / maxDep),
      itemStyle: { color: g.cor(t), opacity: 0.55, borderColor: g.cor(t), borderWidth: 1.5 },
      emphasis: { focus: 'self', itemStyle: { opacity: 0.9 } },
      label: { show: true, formatter: (p) => p.data[3], position: 'top', distance: 3, fontSize: estreito ? 10 : 11, fontWeight: 600, color: t.text,
        backgroundColor: translucido(t.surface, 0.85), padding: [1, 4], borderRadius: 4 },  // legível mesmo perto de outra bolha
      labelLine: { show: true, length2: 4, lineStyle: { color: t.muted, width: 0.8 } },
      labelLayout: posicionarRotulo,
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
      inRange: { color: [GRADIENTE[2], GRADIENTE[1], '#475569'] }, textStyle: { color: t.muted } },
    series: [
      { type: 'heatmap', data: pontos, itemStyle: { borderColor: t.surface, borderWidth: 1 },
        label: { show: el.clientWidth >= 420, formatter: (p) => Math.round(p.data.value[2]), fontSize: 9 },
        emphasis: { focus: 'self', itemStyle: { borderColor: t.text, borderWidth: 2 } } },
    ],
  }), { tabela: { colunas: ['Partido A', 'Partido B', 'Concordância', 'Votações em comum'],
                  linhas: fora.filter((d) => ordem.indexOf(d.partido_b) > ordem.indexOf(d.partido_a))
                    .map((d) => [d.partido_a, d.partido_b, fmt.pct(d.concordancia_pct), d.votacoes_comuns]) } });
});

// Projetos por partido (autor principal): total ou por deputado; o tooltip mostra o maior autor, porque
// um só deputado pode responder por boa parte do partido
let modoProjetos = 'total';
function desenharProjetos() {
  const porDep = modoProjetos === 'por-deputado';
  const valor = (p) => (porDep ? Math.round((10 * p.projetos) / p.deputados) / 10 : p.projetos);
  const ps = partidos.filter((p) => p.deputados > 0).sort((a, b) => valor(b) - valor(a));
  const qtd = Object.fromEntries(ps.map((p) => [p.sigla_partido, p]));
  const formatter = porDep ? fmt.num1 : fmt.num;
  montar(limpa('graf-projetos'), (t) => {
    const op = barras({ categorias: ps.map((p) => p.sigla_partido), horizontal: true, rotulo: true, formatter, gradiente: 'invertido',
                        series: [{ name: porDep ? 'Projetos por deputado' : 'Projetos', data: ps.map(valor) }] })(t);
    op.yAxis.axisLabel = { ...op.yAxis.axisLabel, formatter: (s) => `${s} (${fmt.num(qtd[s].deputados)})` };
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (xs) => {
      const p = qtd[xs[0].name];
      const maior = p.projetos_maior_autor ? `<br>Maior autor: ${fmt.escapar(p.projetos_maior_autor)} (${fmt.num(p.projetos_maior_autor_qtd)}, ${fmt.pct(p.projetos ? (100 * p.projetos_maior_autor_qtd) / p.projetos : 0)} do partido)` : '';
      return `<b>${fmt.escapar(p.sigla_partido)}</b> · ${fmt.num(p.deputados)} ${p.deputados === 1 ? 'deputado' : 'deputados'}<br>Projetos: <b>${fmt.num(p.projetos)}</b> · ${fmt.num1(p.projetos / p.deputados)} por deputado${maior}`;
    } };
    return op;
  }, { tabela: { colunas: ['Partido', 'Deputados', 'Projetos', 'Por deputado', 'Maior autor'],
                 linhas: ps.map((p) => [p.sigla_partido, p.deputados, p.projetos, fmt.num1(p.projetos / p.deputados), p.projetos_maior_autor ? `${p.projetos_maior_autor} (${p.projetos_maior_autor_qtd})` : '—']) } });
}
document.querySelectorAll('#projetos-modo button').forEach((b) => b.addEventListener('click', () => {
  modoProjetos = b.dataset.modo;
  document.querySelectorAll('#projetos-modo button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  desenharProjetos();
}));
await seguro(document.getElementById('graf-projetos'), desenharProjetos);

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
