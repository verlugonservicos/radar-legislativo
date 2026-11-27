// Glossário: busca instantânea pelos termos e destaque do termo aberto por link (#id).
import { iniciar } from '../app.3b9094f3e7.js';

await iniciar();
const campo = document.getElementById('busca-glossario');
const itens = [...document.querySelectorAll('.glossario__item')];
const secoes = [...document.querySelectorAll('.glossario__secao')];
const info = document.getElementById('glossario-info');
const vazio = document.getElementById('glossario-vazio');
const normalizar = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const indice = itens.map((el) => normalizar(el.dataset.busca));

function filtrar() {
  const q = normalizar(campo.value.trim());
  let n = 0;
  itens.forEach((el, i) => { const ok = !q || indice[i].includes(q); el.hidden = !ok; if (ok) n += 1; });
  secoes.forEach((s) => { s.hidden = !s.querySelector('.glossario__item:not([hidden])'); });
  vazio.hidden = n > 0;
  info.textContent = q ? `${n} termo(s) encontrado(s)` : `${itens.length} termos em ${secoes.length} seções`;
}
campo.addEventListener('input', filtrar);
filtrar();

function destacar() {
  document.querySelectorAll('.glossario__item.is-alvo').forEach((el) => el.classList.remove('is-alvo'));
  const alvo = location.hash ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : null;
  if (alvo?.classList.contains('glossario__item')) { alvo.classList.add('is-alvo'); alvo.scrollIntoView({ block: 'center' }); }
}
window.addEventListener('hashchange', destacar);
destacar();
