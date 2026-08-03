// Provider logo registry (UX-DECISIONS §39): official brand marks for the onboarding
// provider gallery, vendored from the MIT-licensed lobe-icons set (same
// bundled-asset posture as the connector registry — no CDN at runtime). Keys are
// /v1/providers names; unknown names get no mark (the gallery falls back to a
// neutral monogram). PROVIDER_ORDER is the gallery order — recognition first,
// long tail behind the scroll fold.

import anthropic from "./logos/anthropic.svg";
// O provedor local usa a marca própria — o motor (llama.cpp) e os modelos rodam aqui dentro.
import mangabaLocal from "./logos/mangaba.png";
import openai from "./logos/openai.svg";
import gemini from "./logos/gemini.svg";
import fireworks from "./logos/fireworks.svg";
import together from "./logos/together.svg";
import zai from "./logos/zai.svg";
import kimi from "./logos/kimi.svg";
import deepseek from "./logos/deepseek.svg";
import mistral from "./logos/mistral.svg";
import qwen from "./logos/qwen.svg";
import minimax from "./logos/minimax.svg";
import xai from "./logos/xai.svg";
import meta from "./logos/meta.svg";

export const PROVIDER_LOGOS: Record<string, string> = {
  local: mangabaLocal,
  anthropic,
  openai,
  gemini,
  meta,
  fireworks,
  together,
  zai,
  kimi,
  deepseek,
  mistral,
  qwen,
  minimax,
  xai,
};

export const PROVIDER_ORDER = [
  // Local primeiro: é a única opção que um usuário recém-instalado usa sem criar conta
  // em lugar nenhum nem cadastrar cartão.
  "local",
  "anthropic",
  "openai",
  "gemini",
  "meta",
  "fireworks",
  "together",
  "zai",
  "kimi",
  "deepseek",
  "mistral",
  "qwen",
  "minimax",
  "xai",
];

export function providerRank(name: string): number {
  const i = PROVIDER_ORDER.indexOf(name);
  return i === -1 ? PROVIDER_ORDER.length : i;
}
