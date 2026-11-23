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
    categorias: top.map((f) => corta(f.titulo)), horizontal: true, rotulo: true,
    series: [{ name: 'Deputados', data: top.map((f) => f.membros) }],
  }), { tabela: { colunas: ['Frente', 'Deputados', 'Partidos', 'Partido com mais membros'], linhas: top.map((f) => [f.titulo, f.membros, f.partidos_distintos, f.top_partido]) } });
});

await seguro(document.getElementById('graf-sankey'), async () => {
  const bp = (await dados('blocos_partidos')).filter((d) => d.membros > 0);
  if (!bp.length) { limpa('graf-sankey').innerHTML = vazio('Sem blocos vigentes com deputados em exercício.'); return; }
  const nos = [...new Set([...bp.map((d) => d.partido), ...bp.map((d) => d.bloco)])].map((name, i) => ({ name, itemStyle: { color: PALETA[i % PALETA.length] } }));
  montar(limpa('graf-sankey'), (t) => ({
    tooltip: { trigger: 'item', formatter: (p) => (p.dataType === 'edge' ? `${fmt.escapar(p.data.source)} → ${fmt.escapar(p.data.target)}: <b>${fmt.num(p.data.value)}</b> deputados` : fmt.escapar(p.name)) },
    series: [{
      type: 'sankey', left: 8, right: 140, top: 8, bottom: 8, nodeGap: 6, emphasis: { focus: 'adjacency' },
      label: { color: t.text, fontSize: 11, formatter: (p) => (p.name.length > 28 ? `${p.name.slice(0, 26)}…` : p.name) },
      lineStyle: { color: 'gradient', opacity: 0.35 }, data: nos,
      links: bp.map((d) => ({ source: d.partido, target: d.bloco, value: d.membros })),
    }],
  }), { tabela: { colunas: ['Partido', 'Bloco', 'Deputados'], linhas: bp.map((d) => [d.partido, d.bloco, d.membros]) } });
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
