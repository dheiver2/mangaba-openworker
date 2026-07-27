// Agendamento em linguagem natural (PT-BR) → cron de 5 campos.
//
// "toda sexta às 17h", "dias úteis às 9", "a cada 2 horas", "todo dia 07:30" —
// o usuário descreve como falaria, e o formulário de automação mostra a leitura
// de volta ("Sextas às 17:00") antes de criar. Nenhum concorrente de desktop faz
// isso em português. Determinístico e local: nada de modelo no caminho.

export interface AgendaPt {
  cron: string;
  /** Releitura humana do que foi entendido — o usuário confirma pelo texto. */
  descricao: string;
}

const DIAS: [RegExp, string, string][] = [
  [/\b(segundas?(-feiras?)?)\b/, "1", "Segundas"],
  [/\b(ter[çc]as?(-feiras?)?)\b/, "2", "Terças"],
  [/\b(quartas?(-feiras?)?)\b/, "3", "Quartas"],
  [/\b(quintas?(-feiras?)?)\b/, "4", "Quintas"],
  [/\b(sextas?(-feiras?)?)\b/, "5", "Sextas"],
  [/\bs[áa]bados?\b/, "6", "Sábados"],
  [/\bdomingos?\b/, "0", "Domingos"],
];

function horario(texto: string): { h: number; m: number } | null {
  // Só aceita a forma com "às"/":"/"h" — um número solto ("a cada 2 horas")
  // não pode virar horário por engano.
  const comAs = texto.match(/[àa]s?\s+(\d{1,2})(?::(\d{2})|h(\d{2})?)?/);
  const comH = texto.match(/\b(\d{1,2})(?::(\d{2})|h(\d{2}))\b/);
  const m = comAs || comH;
  if (!m) return null;
  const h = parseInt(m[1], 10);
  const min = parseInt(m[2] || m[3] || "0", 10);
  if (h > 23 || min > 59) return null;
  return { h, m: min };
}

const fmt = (h: number, m: number) =>
  `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;

export function parseAgendaPt(entrada: string): AgendaPt | null {
  const texto = entrada
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // sem acentos, as regexes ficam simples
    .trim();
  if (!texto) return null;

  // "a cada N horas/minutos" — intervalo, não horário fixo.
  const cada = texto.match(/a cada (\d{1,2}) ?(horas?|minutos?|h|min)\b/);
  if (cada) {
    const n = parseInt(cada[1], 10);
    if (cada[2].startsWith("h") && n >= 1 && n <= 23)
      return { cron: `0 */${n} * * *`, descricao: `A cada ${n} hora${n > 1 ? "s" : ""}` };
    if (!cada[2].startsWith("h") && n >= 5 && n <= 59)
      return { cron: `*/${n} * * * *`, descricao: `A cada ${n} minutos` };
    return null;
  }

  const hm = horario(texto) ?? { h: 9, m: 0 }; // sem horário → 9h, dito na releitura
  const semHora = horario(texto) === null;
  const sufixo = ` às ${fmt(hm.h, hm.m)}${semHora ? " (padrão)" : ""}`;

  if (/dias? uteis|dia util|de segunda a sexta/.test(texto))
    return { cron: `${hm.m} ${hm.h} * * 1-5`, descricao: `Dias úteis${sufixo}` };
  if (/fins? de semana|final de semana/.test(texto))
    return { cron: `${hm.m} ${hm.h} * * 0,6`, descricao: `Fins de semana${sufixo}` };
  if (/todo dia|todos os dias|diariamente|cada dia/.test(texto))
    return { cron: `${hm.m} ${hm.h} * * *`, descricao: `Todo dia${sufixo}` };

  // "toda sexta", "às segundas", "segunda e quinta"…
  const achados = DIAS.filter(([re]) => re.test(texto));
  if (achados.length > 0) {
    const dows = achados.map(([, dow]) => dow).join(",");
    const nomes = achados.map(([, , nome]) => nome);
    const rotulo =
      nomes.length === 1
        ? nomes[0]
        : nomes.slice(0, -1).join(", ") + " e " + nomes[nomes.length - 1];
    return { cron: `${hm.m} ${hm.h} * * ${dows}`, descricao: `${rotulo}${sufixo}` };
  }

  // Só um horário ("às 17h") → todo dia nesse horário.
  if (!semHora) return { cron: `${hm.m} ${hm.h} * * *`, descricao: `Todo dia${sufixo}` };
  return null;
}
