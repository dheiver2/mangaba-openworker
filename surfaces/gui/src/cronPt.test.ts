// O agendador em português: o que a pessoa digita → o cron que o servidor roda.
import { describe, expect, it } from "vitest";
import { parseAgendaPt } from "./cronPt";

describe("parseAgendaPt", () => {
  it("toda sexta às 17h", () => {
    expect(parseAgendaPt("toda sexta às 17h")).toEqual({
      cron: "0 17 * * 5",
      descricao: "Sextas às 17:00",
    });
  });

  it("dias úteis às 9 (com e sem acento)", () => {
    expect(parseAgendaPt("dias úteis às 9")?.cron).toBe("0 9 * * 1-5");
    expect(parseAgendaPt("dias uteis as 9")?.cron).toBe("0 9 * * 1-5");
  });

  it("todo dia 07:30 e diariamente às 8h15", () => {
    expect(parseAgendaPt("todo dia às 07:30")?.cron).toBe("30 7 * * *");
    expect(parseAgendaPt("diariamente às 8h15")?.cron).toBe("15 8 * * *");
  });

  it("fins de semana às 10", () => {
    expect(parseAgendaPt("fins de semana às 10")?.cron).toBe("0 10 * * 0,6");
  });

  it("mais de um dia: segunda e quinta às 14h", () => {
    const out = parseAgendaPt("segunda e quinta às 14h");
    expect(out?.cron).toBe("0 14 * * 1,4");
    expect(out?.descricao).toBe("Segundas e Quintas às 14:00");
  });

  it("a cada 2 horas e a cada 30 minutos", () => {
    expect(parseAgendaPt("a cada 2 horas")?.cron).toBe("0 */2 * * *");
    expect(parseAgendaPt("a cada 30 minutos")?.cron).toBe("*/30 * * * *");
  });

  it("sem horário assume 9h e AVISA na releitura", () => {
    const out = parseAgendaPt("toda segunda");
    expect(out?.cron).toBe("0 9 * * 1");
    expect(out?.descricao).toContain("(padrão)");
  });

  it("só um horário vira todo dia naquele horário", () => {
    expect(parseAgendaPt("às 17h")?.cron).toBe("0 17 * * *");
  });

  it("entrada sem sentido devolve null, nunca um cron chutado", () => {
    expect(parseAgendaPt("quando der")).toBeNull();
    expect(parseAgendaPt("")).toBeNull();
    expect(parseAgendaPt("às 25h")).toBeNull();
  });

  it("sábado e domingo com acento", () => {
    expect(parseAgendaPt("todo sábado às 11h")?.cron).toBe("0 11 * * 6");
    expect(parseAgendaPt("domingos às 20:00")?.cron).toBe("0 20 * * 0");
  });
});
