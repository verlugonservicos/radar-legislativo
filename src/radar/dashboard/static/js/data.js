// Carga dos datasets exportados pelo build: data/<nome>.json → {meta, dados}.
const cache = new Map();
export function carregar(nome) {
  if (!cache.has(nome)) {
    const baixar = (arquivo) => fetch(`data/${arquivo}`, { cache: 'no-cache' }).then((r) => {
      if (!r.ok) throw new Error(`${arquivo}: HTTP ${r.status}`);
      return r.json();
    });
    cache.set(nome, baixar(`${nome}.json`).then(async (j) => {
      // dataset dividido em partes (cada arquivo ≤ 1 MB): baixa as demais e junta (lista ou dicionário)
      if (j.meta?.partes?.length > 1) {
        const resto = await Promise.all(j.meta.partes.slice(1).map(baixar));
        j = { ...j, dados: Array.isArray(j.dados) ? j.dados.concat(...resto.map((p) => p.dados))
          : Object.assign({}, j.dados, ...resto.map((p) => p.dados)) };
      }
      // formato colunar (datasets grandes): remonta os objetos a partir de meta.colunas
      const cols = j.meta?.colunas;
      return cols ? { ...j, dados: j.dados.map((l) => Object.fromEntries(cols.map((c, i) => [c, l[i]]))) } : j;
    }));
  }
  return cache.get(nome);
}
export const dados = async (nome) => (await carregar(nome)).dados;
export const meta = () => dados('meta');
