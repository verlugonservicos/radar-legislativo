// Estado dos filtros sincronizado com a query string (links compartilháveis) — SPEC V3 12.2.
const LISTAS = ['temas', 'partidos', 'ufs'];
export function ler() {
  const q = new URLSearchParams(location.search);
  const estado = { periodo: Number(q.get('periodo')) || 30 };
  for (const k of LISTAS) estado[k] = q.get(k) ? q.get(k).split(',').filter(Boolean) : [];
  if (q.get('busca')) estado.busca = q.get('busca');
  return estado;
}
export function gravar(parcial) {
  const estado = { ...ler(), ...parcial };
  const q = new URLSearchParams();
  if (estado.periodo && estado.periodo !== 30) q.set('periodo', estado.periodo);
  for (const k of LISTAS) if (estado[k]?.length) q.set(k, estado[k].join(','));
  if (estado.busca) q.set('busca', estado.busca);
  const url = `${location.pathname}${q.toString() ? `?${q}` : ''}`;
  history.replaceState(null, '', url);
  document.dispatchEvent(new CustomEvent('radar:filters', { detail: estado }));
  return estado;
}
export const aoMudar = (fn) => document.addEventListener('radar:filters', (e) => fn(e.detail));
