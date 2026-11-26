/**
 * Limites do painel lateral, compartilhados entre o hook do cliente (`usePanelSize`) e o
 * script inline do layout, que aplica a largura salva antes da primeira pintura.
 */

export type Axis = "x" | "y";

/** Menor largura em que a linha de controles cabe sem quebrar (294px de conteúdo + 32px de padding + folga). */
export const SIDEBAR_MIN_X = 328;
export const SIDEBAR_DEFAULT_X = 340;
export const SIDEBAR_MAX_X = 720;
/** Fração da largura da janela que o painel pode ocupar no máximo. */
export const SIDEBAR_MAX_X_RATIO = 0.6;

export const storageKey = (axis: Axis) => `korda.panel.${axis}`;

/** Variável CSS com a largura salva, lida pelo HTML do servidor antes da hidratação. */
export const PANEL_X_VAR = "--panel-x";

export const maxX = (vw: number) =>
  Math.max(SIDEBAR_MIN_X, Math.min(SIDEBAR_MAX_X, Math.round(vw * SIDEBAR_MAX_X_RATIO)));

/**
 * Roda de forma síncrona no <head>: lê a largura salva, aplica os mesmos limites do hook
 * e grava em `--panel-x` no <html>. Assim o HTML do servidor já pinta com a largura
 * certa, e a hidratação não muda nada visualmente.
 */
export const panelInitScript = `(function(){try{var v=Number(localStorage.getItem(${JSON.stringify(
  storageKey("x"),
)}));if(!isFinite(v)||v<=0)return;var w=innerWidth,max=Math.max(${SIDEBAR_MIN_X},Math.min(${SIDEBAR_MAX_X},Math.round(w*${SIDEBAR_MAX_X_RATIO})));document.documentElement.style.setProperty(${JSON.stringify(
  PANEL_X_VAR,
)},Math.min(max,Math.max(${SIDEBAR_MIN_X},v))+"px")}catch(e){}})()`;
