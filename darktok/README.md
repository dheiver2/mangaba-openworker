# DarkTok 🌙

**TikTok-like app by Mangaba.ai**

DarkTok é um aplicativo estilo TikTok com tema escuro, integrado ao ecossistema Mangaba.ai.

## 🚀 Funcionalidades

- **Feed de Vídeos** - Interface tipo TikTok com scroll vertical
- **Curtidas e Comentários** - Interações sociais em tempo real
- **Explorar** - Descubra novos conteúdos
- **Notificações** - Acompanhe suas atividades
- **Perfil** - Gerencie sua conta
- **Tema Dark** - Design escuro com cores mangaba.ai

## 🎨 Identidade Visual

- **Cor Principal**: `#F5861D` (Mangaba Orange)
- **Fundo**: `#0D0D0D` (Dark)
- **Superfície**: `#1A1A1A`
- **Texto**: `#FFFFFF`
- **Verde**: `#2D7D3A` (Mangaba Green)

## 📦 Instalação

```bash
# Instalar dependências
npm install

# Iniciar desenvolvimento
npm run dev

# Build para produção
npm run build
```

## 🖥️ Desktop App (Tauri)

```bash
# Instalar dependências do Tauri
npm install

# Iniciar em modo desenvolvimento
npm run tauri dev

# Build para produção
npm run tauri build
```

## 🏗️ Estrutura do Projeto

```
darktok/
├── src/
│   ├── components/
│   │   ├── VideoFeed.tsx    # Feed principal de vídeos
│   │   ├── Sidebar.tsx      # Menu lateral
│   │   └── Header.tsx       # Cabeçalho
│   ├── App.tsx              # Componente principal
│   ├── main.tsx             # Entry point
│   └── index.css            # Estilos globais
├── src-tauri/               # Configuração Tauri
├── package.json
└── vite.config.ts
```

## 🎯 Tecnologias

- **React 18** - UI Library
- **TypeScript** - Type Safety
- **Vite** - Build Tool
- **Tailwind CSS** - Styling
- **Tauri** - Desktop App
- **Lucide React** - Icons

## 📱 Responsivo

O app é otimizado para:
- Desktop (janela principal)
- Mobile (layout adaptativo)

## 🔗 Integração Mangaba

DarkTok faz parte do ecossistema Mangaba.ai, um assistente AI que vive na sua mesa de trabalho e entrega trabalho pronto.

---

**Feito com 💜 por Mangaba.ai**
