# Mangaba 0.1.49

## App do macOS agora é assinado

O app passa a ser assinado com Developer ID de verdade (não mais build sem assinatura).
A notarização da Apple — que elimina de vez o diálogo do Gatekeeper na primeira
abertura — entra na próxima versão; nesta, a primeira abertura ainda pede o caminho de
sempre (clique direito → Abrir).

## Windows testado em Windows de verdade, a cada release

A partir desta versão, todo instalador do Windows publicado é automaticamente instalado
e executado numa máquina Windows real antes de você: o teste confere que o app abre, o
motor interno sobe e a interface conversa com ele. A ressalva antiga ("cross-compilado,
nunca testado em Windows") caiu — o que continua fora do teste é a aparência visual da
interface.

## Ressalvas (agora menores)

DMG assinado mas ainda sem notarização (diálogo do Gatekeeper na primeira abertura);
instalador do Windows sem assinatura de código (aviso do SmartScreen).
