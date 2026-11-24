// Componentes de interface: tema, navegação, toast, chips, KPI, tabela, drawer, estados vazios.
import * as fmt from './format.js';
import { corTema, montar, redesenharTodos, sparkline } from './charts.js';

// ------------------------------------------------------------------ tema claro/escuro
const CHAVE_TEMA = 'radar-tema';
function lerPreferencia() { try { return localStorage.getItem(CHAVE_TEMA); } catch { return null; } }
function gravarPreferencia(v) { try { localStorage.setItem(CHAVE_TEMA, v); } catch { /* modo privado */ } }
export function temaEfetivo() {
  const attr = document.documentElement.dataset.theme;
  if (attr) return attr;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function aplicarTema(tema) {
  document.documentElement.dataset.theme = tema;
  const botao = document.querySelector('[data-action="tema"]');
  if (botao) {
    botao.setAttribute('aria-label', tema === 'dark' ? 'Usar tema claro' : 'Usar tema escuro');
    botao.setAttribute('aria-pressed', String(tema === 'dark'));
  }
}

// ------------------------------------------------------------------ shell
export function iniciarShell() {
  const pref = lerPreferencia();
  if (pref) aplicarTema(pref); else aplicarTema(temaEfetivo());
  const app = document.querySelector('.app');
  document.querySelector('[data-action="tema"]')?.addEventListener('click', () => {
    const novo = temaEfetivo() === 'dark' ? 'light' : 'dark';
    aplicarTema(novo); gravarPreferencia(novo); redesenharTodos();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (!lerPreferencia()) { aplicarTema(temaEfetivo()); redesenharTodos(); }
  });
  const menu = document.querySelector('[data-action="menu"]');
  const fecharMenu = () => { app.classList.remove('is-open'); menu?.setAttribute('aria-expanded', 'false'); };
  menu?.addEventListener('click', () => {
    const aberto = app.classList.toggle('is-open'); menu.setAttribute('aria-expanded', String(aberto));
    if (aberto) document.querySelector('.nav a')?.focus();
  });
  document.querySelector('.scrim')?.addEventListener('click', fecharMenu);
  document.querySelector('[data-action="recolher"]')?.addEventListener('click', (e) => {
    const recolhido = app.classList.toggle('is-collapsed');
    e.currentTarget.setAttribute('aria-expanded', String(!recolhido));
    setTimeout(redesenharTodos, 200);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { fecharMenu(); fecharDrawer(); } });
}

export function badgeAtualizacao(meta) {
  const el = document.querySelector('[data-update]');
  if (!el || !meta.atualizado_em) return;
  el.querySelector('[data-update-text]').textContent = `Atualizado ${fmt.relativo(meta.atualizado_em)}`;
  el.title = `Última execução do pipeline: ${fmt.dataHora(meta.atualizado_em)} · dados até ${fmt.data(meta.periodo.fim)}`;
}

// ------------------------------------------------------------------ toast
let timerToast;
export function toast(msg) {
  let el = document.querySelector('.toast');
  if (!el) { el = document.createElement('div'); el.className = 'toast'; el.setAttribute('role', 'status'); document.body.append(el); }
  el.textContent = msg; el.classList.add('is-visible');
  clearTimeout(timerToast); timerToast = setTimeout(() => el.classList.remove('is-visible'), 4000);
}

// ------------------------------------------------------------------ pequenos componentes
export const chipTema = (tema) => (tema
  ? `<span class="chip"><span class="chip__dot" style="background:${corTema(tema)}"></span>${fmt.escapar(tema)}</span>` : '');
export const badgeImpacto = (n) => (n ? `<span class="badge badge--${n}">${n === 'medio' ? 'médio' : n}</span>` : '<span class="badge badge--neutro">—</span>');
export const badgeStatus = (s) => `<span class="badge badge--${fmt.escapar(s)}">${fmt.escapar(s)}</span>`;
export const vazio = (msg = 'Sem dados para os filtros selecionados') => `<div class="empty">${fmt.escapar(msg)}</div>`;
export function erro(el, e) { if (el) el.innerHTML = vazio(`Não foi possível carregar os dados (${e.message}).`); console.error(e); }

/** KPI com valor, variação (Δ%) e sparkline. */
export function kpi(el, { valor, anterior, serie, formatter = fmt.num, dica }) {
  if (!el) return;
  const delta = anterior ? ((valor - anterior) / anterior) * 100 : null;
  const classe = delta === null || Math.abs(delta) < 0.5 ? 'is-flat' : delta > 0 ? 'is-up' : 'is-down';
  const seta = classe === 'is-up' ? '▲' : classe === 'is-down' ? '▼' : '•';
  el.querySelector('.kpi__value').textContent = formatter(valor);
  el.querySelector('.kpi__delta').className = `kpi__delta ${classe}`;
  el.querySelector('.kpi__delta').innerHTML = delta === null ? '<small>sem base de comparação</small>'
    : `${seta} ${fmt.num1(Math.abs(delta))}% <small>vs. 7 dias antes</small>`;
  if (dica) el.querySelector('.kpi__hint').textContent = dica;
  const spark = el.querySelector('.kpi__spark');
  if (spark && serie?.length) { spark.classList.remove('skeleton'); montar(spark, sparkline(serie)); spark.setAttribute('aria-label', 'Tendência diária'); }
}

// ------------------------------------------------------------------ tabela
/**
 * Tabela com busca, ordenação por coluna, paginação (25/50/100) e exportação CSV.
 * colunas: [{chave, titulo, num?, render?(linha), valor?(linha), buscavel?}]
 */
export class Tabela {
  constructor(el, { colunas, linhas, porPagina = 25, aoClicar, nomeCsv = 'dados', filtroExtra }) {
    Object.assign(this, { el, colunas, todas: linhas, porPagina, aoClicar, nomeCsv, filtroExtra });
    this.busca = ''; this.pagina = 0; this.ordem = null; this.dir = 1;
    el.innerHTML = `
      <div class="table-tools">
        <label class="sr-only" for="${el.id}-busca">Buscar</label>
        <input class="input" type="search" id="${el.id}-busca" placeholder="Buscar…" autocomplete="off">
        <label class="sr-only" for="${el.id}-pp">Linhas por página</label>
        <select class="select" id="${el.id}-pp"><option>25</option><option>50</option><option>100</option></select>
        <button class="btn" type="button" data-csv>Exportar CSV</button>
      </div>
      <div class="table-wrap"><table class="data"><thead></thead><tbody></tbody></table></div>
      <div class="table-foot"><span data-info></span><div class="pager">
        <button class="btn" type="button" data-prev>Anterior</button><button class="btn" type="button" data-next>Próxima</button></div></div>`;
    el.querySelector('input').addEventListener('input', (e) => { this.busca = e.target.value.toLowerCase(); this.pagina = 0; this.render(); });
    el.querySelector('select').addEventListener('change', (e) => { this.porPagina = Number(e.target.value); this.pagina = 0; this.render(); });
    el.querySelector('[data-prev]').addEventListener('click', () => { this.pagina = Math.max(0, this.pagina - 1); this.render(); });
    el.querySelector('[data-next]').addEventListener('click', () => { this.pagina += 1; this.render(); });
    el.querySelector('[data-csv]').addEventListener('click', () => this.csv());
    this.cabecalho(); this.render();
  }
  valor(c, l) { return c.valor ? c.valor(l) : l[c.chave]; }
  cabecalho() {
    const th = this.colunas.map((c, i) => `<th scope="col" class="${c.num ? 'num' : ''}" aria-sort="${this.ordem === i ? (this.dir > 0 ? 'ascending' : 'descending') : 'none'}">
      <button type="button" data-col="${i}">${fmt.escapar(c.titulo)}<span aria-hidden="true">${this.ordem === i ? (this.dir > 0 ? '▲' : '▼') : ''}</span></button></th>`).join('');
    this.el.querySelector('thead').innerHTML = `<tr>${th}</tr>`;
    this.el.querySelectorAll('thead button').forEach((b) => b.addEventListener('click', () => {
      const i = Number(b.dataset.col); this.dir = this.ordem === i ? -this.dir : (this.colunas[i].num ? -1 : 1); this.ordem = i; this.cabecalho(); this.render();
    }));
  }
  filtradas() {
    let ls = this.filtroExtra ? this.todas.filter(this.filtroExtra) : this.todas;
    if (this.busca) {
      ls = ls.filter((l) => this.colunas.some((c) => c.buscavel !== false && String(this.valor(c, l) ?? '').toLowerCase().includes(this.busca)));
    }
    if (this.ordem !== null) {
      const c = this.colunas[this.ordem];
      ls = [...ls].sort((a, b) => {
        const va = this.valor(c, a); const vb = this.valor(c, b);
        if (va === vb) return 0; if (va === null || va === undefined) return 1; if (vb === null || vb === undefined) return -1;
        return (va > vb ? 1 : -1) * this.dir;
      });
    }
    return ls;
  }
  atualizar(linhas) { if (linhas) this.todas = linhas; this.pagina = 0; this.render(); }
  render() {
    const ls = this.filtradas();
    const paginas = Math.max(1, Math.ceil(ls.length / this.porPagina));
    this.pagina = Math.min(this.pagina, paginas - 1);
    const fatia = ls.slice(this.pagina * this.porPagina, (this.pagina + 1) * this.porPagina);
    const tbody = this.el.querySelector('tbody');
    tbody.innerHTML = fatia.length ? fatia.map((l, i) => `<tr class="${this.aoClicar ? 'is-clickable' : ''}" data-i="${i}" ${this.aoClicar ? 'tabindex="0"' : ''}>${this.colunas.map((c) => {
      const conteudo = c.render ? c.render(l) : fmt.escapar(c.num ? fmt.num(this.valor(c, l)) : this.valor(c, l) ?? '—');
      // texto longo: até 3 linhas na tabela, completo no tooltip (title)
      const corpo = c.clip ? `<div class="clip3" title="${fmt.escapar(this.valor(c, l) ?? '')}">${conteudo}</div>` : conteudo;
      return `<td class="${c.num ? 'num' : ''} ${c.clip ? 'cell-clip' : ''}">${corpo}</td>`;
    }).join('')}</tr>`).join('') : `<tr><td colspan="${this.colunas.length}">${vazio()}</td></tr>`;
    if (this.aoClicar) {
      tbody.querySelectorAll('tr[data-i]').forEach((tr) => {
        const abrir = () => this.aoClicar(fatia[Number(tr.dataset.i)]);
        tr.addEventListener('click', abrir);
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') abrir(); });
      });
    }
    this.el.querySelector('[data-info]').textContent = `${fmt.num(ls.length)} linhas · página ${this.pagina + 1} de ${paginas}`;
    this.el.querySelector('[data-prev]').disabled = this.pagina === 0;
    this.el.querySelector('[data-next]').disabled = this.pagina >= paginas - 1;
  }
  csv() {
    const ls = this.filtradas();
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const texto = [this.colunas.map((c) => esc(c.titulo)).join(';'), ...ls.map((l) => this.colunas.map((c) => esc(this.valor(c, l))).join(';'))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([`﻿${texto}`], { type: 'text/csv;charset=utf-8' }));
    a.download = `${this.nomeCsv}.csv`; a.click(); URL.revokeObjectURL(a.href);
    toast(`${fmt.num(ls.length)} linhas exportadas`);
  }
}

// ------------------------------------------------------------------ drawer
let ultimoFoco;
export function abrirDrawer(html, titulo = 'Detalhe') {
  let d = document.querySelector('.drawer');
  if (!d) {
    d = document.createElement('div'); d.className = 'drawer';
    d.innerHTML = `<div class="drawer__scrim"></div><aside class="drawer__panel" role="dialog" aria-modal="true" tabindex="-1">
      <button class="icon-btn drawer__close" type="button" aria-label="Fechar">✕</button><div class="drawer__body"></div></aside>`;
    document.body.append(d);
    d.querySelector('.drawer__scrim').addEventListener('click', fecharDrawer);
    d.querySelector('.drawer__close').addEventListener('click', fecharDrawer);
  }
  ultimoFoco = document.activeElement;
  d.querySelector('.drawer__panel').setAttribute('aria-label', titulo);
  d.querySelector('.drawer__body').innerHTML = html;
  d.classList.add('is-open');
  d.querySelector('.drawer__panel').focus();
  return d.querySelector('.drawer__body');
}
export function fecharDrawer() {
  const d = document.querySelector('.drawer');
  if (d?.classList.contains('is-open')) { d.classList.remove('is-open'); ultimoFoco?.focus?.(); }
}

/** Botões de período (7/30/90 dias) num container .seg */
export function seletorPeriodo(el, atual, aoMudar) {
  if (!el) return;
  el.innerHTML = [7, 30, 90].map((d) => `<button type="button" data-d="${d}" aria-pressed="${d === atual}">${d} dias</button>`).join('');
  el.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    el.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    aoMudar(Number(b.dataset.d));
  }));
}
