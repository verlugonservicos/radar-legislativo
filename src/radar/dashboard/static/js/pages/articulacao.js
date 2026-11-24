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
  // colunas: partidos (0) · federações que entram num bloco (1) · destinos finais, à direita (2)
  const coluna = (n) => (tipo(n) === 'partido' ? 0 : sai.has(n) ? 1 : 2);
  const nosCom = (t) => nomes.map((name, i) => ({ name, depth: coluna(name),
    itemStyle: { color: PALETA[i % PALETA.length] },
    label: coluna(name) === 0 ? { position: 'left' }                    // partido: nome e número à esquerda
      : coluna(name) === 1 ? { backgroundColor: translucido(t.surface, 0.9), padding: [2, 4], borderRadius: 4 }  // cruza as faixas
      : {} }));
  const el = limpa('graf-sankey');
  const COLUNA = 190;  // coluna da direita: nome da federação/bloco + somatório alinhado na borda
  montar(el, (t) => ({
    tooltip: { trigger: 'item', formatter: (p) => (p.dataType === 'edge'
      ? `${fmt.escapar(p.data.source)} → ${fmt.escapar(p.data.target)}: <b>${fmt.num(p.data.value)}</b> deputados`
      : `<b>${fmt.escapar(p.name)}</b> (${tipo(p.name)})<br>${fmt.num(total(p.name))} deputados em exercício`) },
    series: [{
      type: 'sankey', left: 104, right: COLUNA, top: 8, bottom: 8, nodeGap: 10, nodeWidth: 14,
      nodeAlign: 'right',  // federações sem bloco também vão para a coluna da direita
      emphasis: { focus: 'adjacency' }, layoutIterations: 64,
      label: {
        color: t.text, fontSize: 11,
        formatter: (p) => {
          if (tipo(p.name) === 'partido') return `{n|${p.name}} {q|${fmt.num(total(p.name))}}`;
          const nome = p.name.length > 24 ? `${p.name.slice(0, 22)}…` : p.name;
          return `{d|${nome}}{s|${fmt.num(total(p.name))}}`;
        },
        rich: {
          n: { color: t.text, fontSize: 11 }, q: { color: t.accent, fontSize: 11, fontWeight: 700 },
          // nome com largura fixa + somatório alinhado à direita: os totais formam uma coluna na borda
          d: { color: t.text, fontSize: 11, width: COLUNA - 52, overflow: 'truncate' },
          s: { color: t.accent, fontSize: 12, fontWeight: 700, width: 36, align: 'right' },
        },
      },
      lineStyle: { color: 'gradient', opacity: 0.35 }, data: nosCom(t), links,
    }],
  }), { tabela: { colunas: ['De', 'Para', 'Deputados'], linhas: links.map((l) => [l.source, l.target, l.value]) } });
});

function translucido(hex, a) {
  return /^#[0-9a-f]{6}$/i.test(hex)
    ? `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})` : hex;
}

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
