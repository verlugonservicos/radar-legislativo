// Inicialização comum a todas as páginas: shell, tema, metadados e cores dos temas.
import { meta } from './data.4fb3031e8e.js';
import { definirCoresTemas } from './charts.83ed569f4b.js';
import { badgeAtualizacao, iniciarShell, toast } from './ui.6a7de658b0.js';
import * as fmt from './format.20a0ca273f.js';

export async function iniciar() {
  iniciarShell();
  try {
    const m = await meta();
    definirCoresTemas(m.temas);
    badgeAtualizacao(m);
    document.querySelectorAll('[data-meta="cobertura"]').forEach((el) => { el.textContent = m.cobertura; });
    document.querySelectorAll('[data-meta="periodo"]').forEach((el) => { el.textContent = `${fmt.data(m.periodo.inicio)} a ${fmt.data(m.periodo.fim)}`; });
    document.querySelectorAll('[data-meta="atualizado"]').forEach((el) => { el.textContent = fmt.dataHora(m.atualizado_em); });
    if (m.atualizado_em && Date.now() - new Date(m.atualizado_em).getTime() > 3 * 86400e3) {
      toast(`Dados de ${fmt.dataHora(m.atualizado_em)}`);
    }
    return m;
  } catch (e) {
    console.error(e);
    toast('Não foi possível carregar os metadados do painel.');
    return { temas: [], periodo: {} };
  }
}

/** Executa `fn` e mostra estado de erro no elemento se falhar (um card nunca derruba a página). */
export async function seguro(el, fn) {
  try { await fn(); } catch (e) {
    console.error(e);
    if (el) el.innerHTML = `<div class="empty">Não foi possível montar este painel (${fmt.escapar(e.message)}).</div>`;
  }
}
