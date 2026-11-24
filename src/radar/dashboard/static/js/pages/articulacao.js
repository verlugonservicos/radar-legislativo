// Articulação Política: frentes, partidos nos blocos (sankey), Mesa Diretora e lideranças.
import { iniciar, seguro } from '../app.js';
import { dados } from '../data.js';
import { barras, montar, PALETA } from '../charts.js';
import { Tabela, vazio } from '../ui.js';
import * as fmt from '../format.js';

await iniciar();
const frentes = await dados('articulacao');
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };

await seguro(document.getElementById('graf-frentes'), async () => {
  const top = frentes.slice(0, 20);
  const corta = (t) => t.replace(/^Frente Parlamentar (Mista )?(em |de |da |do |pela |pelo |para )?/i, '').slice(0, 48);
  montar(limpa('graf-frentes'), barras({
    gradiente: 'invertido', categorias: top.map((f) => corta(f.titulo)), horizontal: true, rotulo: true,
    series: [{ name: 'Deputados', data: top.map((f) => f.membros) }],
  }), { tabela: { colunas: ['Frente', 'Deputados', 'Partidos', 'Partido com mais membros'], linhas: top.map((f) => [f.titulo, f.membros, f.partidos_distintos, f.top_partido]) } });
});

await seguro(document.getElementById('graf-sankey'), async () => {
  const bp = (await dados('blocos_partidos')).filter((d) => d.membros > 0);
  if (!bp.length) { limpa('graf-sankey').innerHTML = vazio('Sem blocos vigentes com deputados em exercício.'); return; }
  // 3 níveis: partido → federação → bloco. Uma federação atua como um partido só e pode entrar inteira
  // num bloco; ligar o partido à federação E ao bloco contaria seus deputados duas vezes.
  const ehFederacao = (nome) => /^federa[çc][ãa]o/i.test(nome);
  const federacaoDe = new Map(bp.filter((d) => ehFederacao(d.bloco)).map((d) => [d.partido, d.bloco]));
  const fluxo = new Map();  // "origem→destino" → deputados
  const somar = (a, b, v) => fluxo.set(`${a}\u0000${b}`, (fluxo.get(`${a}\u0000${b}`) || 0) + v);
  for (const d of bp) {
    if (ehFederacao(d.bloco)) somar(d.partido, d.bloco, d.membros);                   // partido → federação
    else if (federacaoDe.has(d.partido)) somar(federacaoDe.get(d.partido), d.bloco, d.membros);  // federação → bloco
    else somar(d.partido, d.bloco, d.membros);                                         // partido → bloco
  }
  const links = [...fluxo].map(([k, value]) => { const [source, target] = k.split('\u0000'); return { source, target, value }; });
  const entra = new Map(); const sai = new Map();
  for (const l of links) { entra.set(l.target, (entra.get(l.target) || 0) + l.value); sai.set(l.source, (sai.get(l.source) || 0) + l.value); }
  const total = (n) => Math.max(entra.get(n) || 0, sai.get(n) || 0);
  const tipo = (n) => (ehFederacao(n) ? 'federação' : entra.has(n) ? 'bloco' : 'partido');
  const nomes = [...new Set(links.flatMap((l) => [l.source, l.target]))];
  const nos = nomes.map((name, i) => ({ name, depth: tipo(name) === 'partido' ? 0 : tipo(name) === 'federação' ? 1 : 2,
    itemStyle: { color: PALETA[i % PALETA.length] },
    // partidos: nome à esquerda da barra, fora das faixas (o número das faixas fica livre)
    ...(tipo(name) === 'partido' ? { label: { position: 'left' } } : {}) }));
  montar(limpa('graf-sankey'), (t) => ({
    tooltip: { trigger: 'item', formatter: (p) => (p.dataType === 'edge'
      ? `${fmt.escapar(p.data.source)} → ${fmt.escapar(p.data.target)}: <b>${fmt.num(p.data.value)}</b> deputados`
      : `<b>${fmt.escapar(p.name)}</b> (${tipo(p.name)})<br>${fmt.num(total(p.name))} deputados em exercício`) },
    series: [{
      type: 'sankey', left: 120, right: 210, top: 8, bottom: 8, nodeGap: 10, nodeWidth: 16, nodeAlign: 'left',
      emphasis: { focus: 'adjacency' }, layoutIterations: 64,
      label: { color: t.text, fontSize: 11, formatter: (p) => {
        const nome = p.name.length > 30 ? `${p.name.slice(0, 28)}…` : p.name;
        return `{n|${nome}} {q|${fmt.num(total(p.name))}}`;
      }, rich: { n: { color: t.text, fontSize: 11 }, q: { color: t.accent, fontSize: 11, fontWeight: 700 } } },
      // o número de deputados escrito dentro de cada faixa de ligação
      // (só nas faixas com espessura para o número; as finas ficam com o número ao lado do partido)
      edgeLabel: { show: true, formatter: (p) => (p.data.value >= 8 ? fmt.num(p.data.value) : ''), fontSize: 12, fontWeight: 700,
        color: t.text, textBorderColor: t.surface, textBorderWidth: 3 },
      lineStyle: { color: 'gradient', opacity: 0.35 }, data: nos, links,
    }],
  }), { tabela: { colunas: ['De', 'Para', 'Deputados'], linhas: links.map((l) => [l.source, l.target, l.value]) } });
});

const cartao = (p) => `<div class="item person"><img class="avatar" src="${fmt.escapar(p.url_foto || '')}" alt="" loading="lazy" width="36" height="36">
  <div><div class="item__title">${fmt.escapar(p.nome)}</div><div class="muted" style="font-size:var(--fs-xs)">${fmt.escapar(p.titulo)}${p.bancada ? ` · ${fmt.escapar(p.bancada)}` : ''}<br>${fmt.escapar(p.sigla_partido || '')}-${fmt.escapar(p.sigla_uf || '')}</div></div></div>`;

await seguro(document.getElementById('lista-mesa'), async () => {
  const l = await dados('liderancas');
  const mesa = l.filter((d) => d.tipo === 'Mesa Diretora');
  const lideres = l.filter((d) => d.tipo !== 'Mesa Diretora');
  document.getElementById('lista-mesa').innerHTML = mesa.map(cartao).join('') || vazio();
  document.getElementById('lista-lideres').innerHTML = lideres.map(cartao).join('') || vazio();
});

await seguro(document.getElementById('tabela-frentes'), async () => {
  new Tabela(document.getElementById('tabela-frentes'), {
    linhas: frentes, nomeCsv: 'frentes',
    colunas: [
      { chave: 'titulo', titulo: 'Frente', clip: true },
      { chave: 'membros', titulo: 'Deputados', num: true },
      { chave: 'partidos_distintos', titulo: 'Partidos', num: true },
      { chave: 'top_partido', titulo: 'Partido com mais membros' },
      { chave: 'coordenador', titulo: 'Coordenação' },
    ],
  });
});
