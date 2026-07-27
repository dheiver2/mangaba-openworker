// Espelho em TS do protetor de segredos (mangaba/guardrails.py).
//
// A fronteira de SEGURANÇA é o servidor — ele redige de novo, sempre. Este espelho
// existe pela honestidade da UI: sem ele, o eco local da mensagem mostraria a chave
// que o servidor removeu, e a bolha duplicaria quando o turn_start devolvesse a
// versão redigida. Ao alterar um padrão, altere NOS DOIS arquivos.

export const PLACEHOLDER = "[SEGREDO REMOVIDO PELO MANGABA]";

const PADROES: RegExp[] = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
  /\bsk-ant-[A-Za-z0-9_-]{20,}\b/g,
  /\bsk-[A-Za-z0-9_-]{20,}\b/g,
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{30,}\b/g,
  /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g,
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\bhf_[A-Za-z0-9]{30,}\b/g,
  /\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b/g,
  /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g,
];

const ATRIBUICAO =
  /\b([A-Za-z0-9_]*(?:password|passwd|senha|api[_-]?key|secret|token))\s*[=:]\s*['"]?([^\s'"]{8,})/gi;

export function redactSecrets(texto: string): { texto: string; achados: number } {
  if (!texto) return { texto, achados: 0 };
  let achados = 0;
  for (const re of PADROES) {
    texto = texto.replace(re, () => {
      achados += 1;
      return PLACEHOLDER;
    });
  }
  texto = texto.replace(ATRIBUICAO, (_m, chave: string) => {
    achados += 1;
    return `${chave}=${PLACEHOLDER}`;
  });
  return { texto, achados };
}
