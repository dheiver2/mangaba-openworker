// UX-015 (§33): chamadas de ferramenta viram frases de uma linha em PT-BR. The model does NOT emit a purpose
// per call — the stream is name+args+result — so the sentence is synthesized here from
// per-tool templates. `run_shell` is the exception: its optional `description` argument is
// model-written intent and is preferred when present. Fallback: "Used <tool> — <short args>".

import { shortArgs } from "./components/ApprovalCard";

// A one-line sentence in three segments so the UI can emphasize the object:
// "Read " + <b>runbook.md</b> + " from the shared folder".
export interface HumanLine {
  pre: string;
  obj?: string;
  post?: string;
  /** Caminho completo por trás de um `obj` encurtado, para o card de aprovação
   *  mostrar no tooltip. Aprovar uma gravação vendo apenas "relatorio.md", sem a
   *  pasta, esconde exatamente a informação que decide se a ação é segura. */
  objTitle?: string;
}

const trunc = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const baseName = (p: string) => p.replace(/\/+$/, "").split("/").pop() || p;

// send_message targets are "platform:chat" or "platform:chat:thread" — show the platform
// by name and the last human-ish segment of the chat id.
function messageTarget(target: string): { platform: string; tail: string } {
  const [platform, ...rest] = String(target).split(":");
  const chat = rest[0] || "";
  const tail = chat.includes("/") ? chat.split("/").pop() || chat : chat;
  const names: Record<string, string> = { slack: "Slack", telegram: "Telegram" };
  return { platform: names[platform] || platform, tail };
}

export function humanizeTool(name: string, args: any): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  switch (name) {
    case "run_shell": {
      const cmd = trunc(String(a.command ?? ""), 60);
      const desc = typeof a.description === "string" && a.description.trim() ? a.description.trim() : "";
      const pre = a.run_in_background ? "Iniciou em segundo plano: " : "Executou ";
      return {
        pre,
        obj: cmd,
        ...(desc ? { post: ` — ${desc.charAt(0).toLowerCase()}${desc.slice(1)}` } : {}),
      };
    }
    case "shell_task_output":
      return { pre: "Verificou um comando em segundo plano" };
    case "shell_task_kill":
      return { pre: "Parou um comando em segundo plano" };
    case "read_file":
      return { pre: "Leu ", obj: baseName(String(a.path ?? "um arquivo")) };
    case "write_file":
      return { pre: "Escreveu ", obj: baseName(String(a.path ?? "um arquivo")) };
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return { pre: "Editou ", obj: a.path ? baseName(String(a.path)) : "arquivos" };
    case "grep":
      return { pre: "Buscou no código por ", obj: `“${trunc(String(a.pattern ?? ""), 40)}”` };
    case "git_log":
      return { pre: "Consultou o histórico recente do git" };
    case "todo_write": {
      // `todos` is current; `items` renders histories from before the rename (the old
      // key breaks Together's GLM-5.2 chat template — see mangaba/tools/todo.py).
      const items = Array.isArray(a.todos) ? a.todos : Array.isArray(a.items) ? a.items : [];
      if (items.length === 1) {
        const it = items[0] || {};
        const status = String(it.status || "").replace(/_/g, " ");
        return {
          pre: "Atualizou o plano — ",
          obj: `“${trunc(String(it.content ?? ""), 70)}”`,
          ...(status ? { post: ` → ${status}` } : {}),
        };
      }
      return { pre: `Atualizou o plano — ${items.length} itens` };
    }
    case "send_message": {
      const { platform, tail } = messageTarget(String(a.target ?? ""));
      if (!tail) return { pre: "Enviou uma mensagem" };
      return { pre: `Enviou uma mensagem no ${platform} para `, obj: tail };
    }
    case "web_search":
      return { pre: "Pesquisou na web — ", obj: `“${trunc(String(a.query ?? ""), 60)}”` };
    case "web_fetch": {
      let host = String(a.url ?? "");
      try {
        host = new URL(host).host || host;
      } catch {
        /* keep raw */
      }
      return { pre: "Leu uma página web — ", obj: trunc(host, 50) };
    }
    case "explore":
      return { pre: "Enviou um subagente para explorar — ", obj: `“${trunc(String(a.task ?? a.prompt ?? ""), 60)}”` };
    case "load_skill":
      // SKILLS-SPEC §4.1 #4 — the trust line: the transcript always shows the moment a
      // skill's instructions were picked up, model-invoked or forced via /skill.
      return { pre: "Usou a skill: ", obj: String(a.name ?? "") };
    case "ask_user":
      return { pre: "Fez uma pergunta a você" };
    case "propose_plan":
      return { pre: "Propôs um plano" };
    case "request_directory":
      return { pre: "Pediu acesso a uma pasta — ", obj: String(a.path ?? "") };
    default: {
      const rest = trunc(shortArgs(a), 80);
      return { pre: `Usou ${name}`, ...(rest ? { post: ` — ${rest}` } : {}) };
    }
  }
}

// The approval card's headline (§35): the ask, phrased as the action being decided.
// run_shell leads with the model's own description ("Run a command — fetch stock data").
export function humanizeApprovalTitle(name: string, args: any): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  switch (name) {
    case "write_file": {
      const caminho = String(a.path ?? "");
      return {
        pre: "Escrever ",
        obj: baseName(caminho || "um arquivo"),
        objTitle: caminho || undefined,
      };
    }
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff": {
      const caminho = a.path ? String(a.path) : "";
      return {
        pre: "Editar ",
        obj: caminho ? baseName(caminho) : "arquivos",
        objTitle: caminho || undefined,
      };
    }
    case "run_shell": {
      const desc = typeof a.description === "string" && a.description.trim() ? a.description.trim() : "";
      return {
        pre: "Rodar um comando",
        ...(desc ? { post: ` — ${desc.charAt(0).toLowerCase()}${desc.slice(1)}` } : {}),
      };
    }
    case "send_message": {
      const { tail } = messageTarget(String(a.target ?? ""));
      return tail ? { pre: "Enviar uma mensagem para ", obj: tail } : { pre: "Enviar uma mensagem" };
    }
    case "send_file": {
      const { tail } = messageTarget(String(a.target ?? ""));
      return tail ? { pre: "Enviar um arquivo para ", obj: tail } : { pre: "Enviar um arquivo" };
    }
    case "create_scheduled_task":
      return a.title
        ? { pre: "Criar a automação ", obj: `“${trunc(String(a.title), 60)}”` }
        : { pre: "Criar uma automação" };
    case "save_skill":
      // SKILLS-SPEC §5.2/§7: "Add", never "install"; destination is "your skills".
      return a.name
        ? { pre: "Adicionar a skill ", obj: String(a.name), post: " às suas skills" }
        : { pre: "Adicionar uma skill às suas skills" };
    default:
      return { pre: `Usar ${name}` };
  }
}

// Approvals with no executed tool call (typically declined): the ask, phrased as intent.
export function humanizeAsk(name: string, args: any): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  switch (name) {
    case "run_shell":
      return { pre: "Queria executar ", obj: trunc(String(a.command ?? ""), 60) };
    case "write_file":
      return { pre: "Queria escrever ", obj: baseName(String(a.path ?? "um arquivo")) };
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return { pre: "Queria editar ", obj: a.path ? baseName(String(a.path)) : "arquivos" };
    case "send_message": {
      const { platform, tail } = messageTarget(String(a.target ?? ""));
      if (!tail) return { pre: "Queria enviar uma mensagem" };
      return { pre: `Queria mandar mensagem para `, obj: tail, post: ` no ${platform}` };
    }
    default:
      return { pre: `Queria usar ${name}` };
  }
}
