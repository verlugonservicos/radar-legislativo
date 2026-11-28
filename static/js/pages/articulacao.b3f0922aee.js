// Articulação Política: frentes, partidos nos blocos (sankey), Mesa Diretora e lideranças.
import { iniciar, seguro } from '../app.3b9094f3e7.js';
import { dados } from '../data.4fb3031e8e.js';
import { barras, montar, PALETA, linhaMedia, mediaDe } from '../charts.83ed569f4b.js';
import { Tabela, vazio } from '../ui.6a7de658b0.js';
import * as fmt from '../format.20a0ca273f.js';

await iniciar();
const frentes = await dados('articulacao');
const limpa = (id) => { const el = document.getElementById(id); el.classList.remove('skeleton'); return el; };

await seguro(document.getElementById('graf-frentes'), async () => {
  const top = frentes.slice(0, 20);
  const corta = (t) => t.replace(/^Frente Parlamentar (Mista )?(em |de |da |do |pela |pelo |para )?/i, '').slice(0, 48);
  // sem percentual: um deputado integra várias frentes, então "% da Câmara" somava mais de 900% e confundia
  montar(limpa('graf-frentes'), (t) => {
    const op = barras({
      gradiente: 'invertido', categorias: top.map((f) => corta(f.titulo)), horizontal: true, rotulo: true,
      series: [{ name: 'Deputados', data: top.map((f) => f.membros) }],
    })(t);
    linhaMedia(op, mediaDe(frentes.map((f) => f.membros)), t, { formatter: fmt.num1 });  // média de todas as frentes
    op.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (xs) => {
      const f = top[xs[0].dataIndex];
      return `<b>${fmt.escapar(f.titulo)}</b><br>Deputados: <b>${fmt.num(f.membros)}</b>`
        + `<br>${fmt.num(f.partidos_distintos)} partidos · mais membros: ${fmt.escapar(f.top_partido || '—')}`;
    } };
    return op;
  }, { tabela: { colunas: ['Frente', 'Deputados', 'Partidos', 'Partido com mais membros'], linhas: top.map((f) => [f.titulo, f.membros, f.partidos_distintos, f.top_partido]) } });
});

await seguro(document.getElementById('graf-sankey'), async () => {
  // % = parcela da Câmara (deputados em exercício) em cada destino final, com 2 casas, fechando 100%
  const partidosCamara = await dados('partidos');
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
  // partidos fora de qualquer bloco/federação viram a linha "Sem bloco": assim o lado direito soma 100%
  // da Câmara (os 19 da federação PSDB CIDADANIA já estão dentro do bloco de 273)
  const SEM_BLOCO = 'Sem bloco';
  const emBloco = new Set(bp.map((d) => d.partido));
  for (const p of partidosCamara) if (p.deputados > 0 && !emBloco.has(p.sigla_partido)) somar(p.sigla_partido, SEM_BLOCO, p.deputados);
  const links = [...fluxo].map(([k, value]) => { const [source, target] = k.split('\u0000'); return { source, target, value }; });
  const entra = new Map(); const sai = new Map();
  for (const l of links) { entra.set(l.target, (entra.get(l.target) || 0) + l.value); sai.set(l.source, (sai.get(l.source) || 0) + l.value); }
  const total = (n) => Math.max(entra.get(n) || 0, sai.get(n) || 0);
  const tipo = (n) => (ehFederacao(n) ? 'federação' : entra.has(n) ? 'bloco' : 'partido');
  const nomes = [...new Set(links.flatMap((l) => [l.source, l.target]))];
  // colunas: partidos (0) · federações que entram num bloco (1) · destinos finais, à direita (2)
  const coluna = (n) => (tipo(n) === 'partido' ? 0 : sai.has(n) ? 1 : 2);
  // a federação do meio (ex.: PSDB CIDADANIA → bloco) é só uma passagem: o nó toma a cor do bloco de
  // destino com a mesma transparência das faixas, emendando-as sem o "quadradinho" solto no meio;
  // o nome e o total dela aparecem na coluna da direita
  const corDe = (n) => PALETA[nomes.indexOf(n) % PALETA.length];
  const destino = (n) => links.find((l) => l.source === n)?.target;
  const nosCom = (t) => nomes.map((name, i) => ({ name, depth: coluna(name),
    itemStyle: coluna(name) === 1 ? { color: corDe(destino(name)), opacity: 0.35, borderWidth: 0 }
      : name === SEM_BLOCO ? { color: '#94A3B8' } : { color: PALETA[i % PALETA.length] },
    label: coluna(name) === 0 ? { position: 'left' }                    // partido: nome e número à esquerda
      // federação intermediária: o rótulo vai para a coluna da direita (na altura do nó), fora das faixas
      : coluna(name) === 1 ? { position: 'right', offset: [deslocamentoMeio(), 0] }
      : {} }));
  const el = limpa('graf-sankey');
  const COLUNA = 190;  // coluna da direita: nome da federação/bloco (o total fica dentro do gráfico)
  // margem esquerda do tamanho do maior rótulo de partido (ex.: "REPUBLICANOS (43)"), medido no canvas,
  // para nenhum nome ser cortado na borda do card
  const medir = document.createElement('canvas').getContext('2d');
  medir.font = `600 11px ${getComputedStyle(document.body).fontFamily}`;
  const ESQ = Math.ceil(Math.max(90, ...nomes.filter((n) => tipo(n) === 'partido')
    .map((n) => medir.measureText(`${n} (${fmt.num(total(n))})`).width)) + 16);
  const LARGURA_NO = 14;
  // distância do nó do meio até a coluna da direita (os nós do meio ficam a meio caminho das colunas)
  const deslocamentoMeio = () => {
    const xDireita = el.clientWidth - COLUNA - LARGURA_NO;
    const xMeio = ESQ + (xDireita - ESQ) / 2;
    return xDireita - xMeio;
  };
  // a posição do rótulo do meio depende da largura: redesenha quando o card muda de tamanho
  let largura = el.clientWidth; let espera;
  new ResizeObserver(() => {
    if (Math.abs(el.clientWidth - largura) < 8) return;
    largura = el.clientWidth; clearTimeout(espera); espera = setTimeout(() => grafico?.redesenhar(), 150);
  }).observe(el);
  const grafico = montar(el, (t) => ({
    tooltip: { trigger: 'item', formatter: (p) => (p.dataType === 'edge'
      ? `${fmt.escapar(p.data.source)} → ${fmt.escapar(p.data.target)}: <b>${fmt.num(p.data.value)}</b> deputados`
      : `<b>${fmt.escapar(p.name)}</b> (${tipo(p.name)})<br>${fmt.num(total(p.name))} deputados em exercício`) },
    series: [{
      type: 'sankey', left: ESQ, right: COLUNA, top: 8, bottom: 8, nodeGap: 10, nodeWidth: LARGURA_NO,
      nodeAlign: 'right',  // federações sem bloco também vão para a coluna da direita
      emphasis: { focus: 'adjacency' }, layoutIterations: 64,
      label: {
        color: t.text, fontSize: 11,
        formatter: (p) => {
          if (tipo(p.name) === 'partido') return `{n|${p.name}} {q|(${fmt.num(total(p.name))})}`;
          return p.name.length > 30 ? `${p.name.slice(0, 28)}…` : p.name;
        },
        rich: {
          n: { color: t.text, fontSize: 11 }, q: { color: t.accent, fontSize: 11, fontWeight: 700 },
        },
      },
      lineStyle: { color: 'gradient', opacity: 0.35 }, data: nosCom(t), links,
    }],
  }), {
    tabela: { colunas: ['De', 'Para', 'Deputados'], linhas: links.map((l) => [l.source, l.target, l.value]) },
    // total de cada federação/bloco dentro da área do gráfico, encostado à esquerda da barra
    depois: (inst, t) => {
      const serie = inst.getModel().getSeriesByIndex(0);
      const grafo = serie.getGraph();
      const { x: x0, y: y0 } = serie.layoutInfo;  // o layout dos nós é relativo à área da série
      const textos = [];
      // a federação do meio tem o nome deslocado para a coluna da direita: o total acompanha o nome
      let xDireita = 0;
      grafo.eachNode((no) => { xDireita = Math.max(xDireita, no.getLayout().x); });
      // total e % só nos destinos finais (blocos, federações fora de bloco e "Sem bloco"), que somam a
      // Câmara inteira e fecham 100,00% exato; a federação de dentro do bloco não ganha total (já está no bloco)
      const destinos = nomes.filter((n) => coluna(n) === 2);
      const pcts = Object.fromEntries(fmt.pctsExatos(destinos.map(total)).map((v, i) => [destinos[i], v]));
      grafo.eachNode((no) => {
        if (!pcts[no.id]) return;  // só destinos finais: a federação de dentro do bloco fica sem total (confundia)
        const { y, dy } = no.getLayout();
        const x = xDireita;
        const rotulo = `${fmt.num(total(no.id))} (${pcts[no.id]})`;
        textos.push({
          type: 'text', x: x0 + x - 8, y: y0 + y + dy / 2, silent: true, z: 100,
          style: { text: rotulo, align: 'right', verticalAlign: 'middle', fontSize: 15, fontWeight: 700,
                   fill: t.text, stroke: t.surface, lineWidth: 4 },
        });
      });
      inst.setOption({ graphic: [{ id: 'totais', type: 'group', children: textos }] }, { replaceMerge: ['graphic'] });
    },
  });
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
