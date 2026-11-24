// Formatação pt-BR (SPEC V3 12.2): números, moeda compacta, percentuais e datas.
const nf = new Intl.NumberFormat('pt-BR');
const nf1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const brlFull = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const brlCompact = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1 });
const dtf = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' });
const dtfShort = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', timeZone: 'UTC' });
const dtfTime = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' });
const rtf = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' });

const vazio = (v) => v === null || v === undefined || Number.isNaN(v);
export const num = (v) => (vazio(v) ? '—' : nf.format(v));
export const num1 = (v) => (vazio(v) ? '—' : nf1.format(v));
export const brl = (v) => (vazio(v) ? '—' : brlCompact.format(v).replace(/ /g, ' '));
export const brlFull_ = (v) => (vazio(v) ? '—' : brlFull.format(v));
export { brlFull_ as brlCheio };
export const pct = (v) => (vazio(v) ? '—' : `${nf1.format(v)}%`);
export const pct2 = (v) => (vazio(v) ? '—' : `${nf2.format(v)}%`);
export const pctFrac = (v) => (vazio(v) ? '—' : `${nf1.format(v * 100)}%`);
export const data = (iso) => (iso ? dtf.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`)) : '—');
export const dataCurta = (iso) => (iso ? dtfShort.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`)).replace('.', '') : '—');
/** Número da semana no ano (ISO 8601: semanas de segunda a domingo; a semana 1 contém a primeira quinta-feira). */
export function semanaAno(iso) {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  const dia = (d.getUTCDay() + 6) % 7;            // segunda = 0
  d.setUTCDate(d.getUTCDate() - dia + 3);         // quinta-feira da mesma semana
  const inicioAno = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((d - inicioAno) / 86_400_000 - 3 + ((inicioAno.getUTCDay() + 6) % 7)) / 7);
}
/** "Semana 29 · 13 de jul a 19 de jul" a partir da segunda-feira (AAAA-MM-DD). */
export function rotuloSemana(segunda) {
  const dom = new Date(Date.parse(`${segunda.slice(0, 10)}T00:00:00Z`) + 6 * 86_400_000).toISOString().slice(0, 10);
  return `Semana ${semanaAno(segunda)} · ${dataCurta(segunda)} a ${dataCurta(dom)}`;
}
export const dataHora = (iso) => (iso ? dtfTime.format(new Date(iso)) : '—');
export function relativo(iso) {
  if (!iso) return '—';
  const seg = (new Date(iso).getTime() - Date.now()) / 1000;
  const passos = [[60, 'second'], [60, 'minute'], [24, 'hour'], [30, 'day'], [12, 'month'], [Infinity, 'year']];
  let v = seg;
  for (const [lim, unidade] of passos) {
    if (Math.abs(v) < lim) return rtf.format(Math.round(v), unidade);
    v /= lim;
  }
  return '';
}
export const proposicao = (p) => `${p.sigla_tipo} ${p.numero}/${p.ano}`;
export const escapar = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
