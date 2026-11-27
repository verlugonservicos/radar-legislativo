// Carga dos datasets exportados pelo build: data/<nome>.json → {meta, dados}.
const cache = new Map();
export function carregar(nome) {
  if (!cache.has(nome)) {
    cache.set(nome, fetch(`data/${nome}.json`, { cache: 'no-cache' }).then((r) => {
      if (!r.ok) throw new Error(`${nome}: HTTP ${r.status}`);
      return r.json();
    }).then((j) => {
      // formato colunar (datasets grandes): remonta os objetos a partir de meta.colunas
      const cols = j.meta?.colunas;
      return cols ? { ...j, dados: j.dados.map((l) => Object.fromEntries(cols.map((c, i) => [c, l[i]]))) } : j;
    }));
  }
  return cache.get(nome);
}
export const dados = async (nome) => (await carregar(nome)).dados;
export const meta = () => dados('meta');
