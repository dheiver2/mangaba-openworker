import { Home, Search, Bell, User, PlusSquare, Settings, LogOut } from 'lucide-react'

interface SidebarProps {
  currentView: 'feed' | 'explore' | 'notifications' | 'profile'
  setCurrentView: (view: 'feed' | 'explore' | 'notifications' | 'profile') => void
}

export default function Sidebar({ currentView, setCurrentView }: SidebarProps) {
  const menuItems = [
    { id: 'feed' as const, icon: Home, label: 'Início' },
    { id: 'explore' as const, icon: Search, label: 'Explorar' },
    { id: 'notifications' as const, icon: Bell, label: 'Notificações' },
    { id: 'profile' as const, icon: User, label: 'Perfil' },
  ]

  return (
    <aside className="w-64 h-screen bg-mangaba-surface border-r border-mangaba-orange/20 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-mangaba-orange/20">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-mangaba-orange rounded-xl flex items-center justify-center">
            <span className="text-white font-bold text-xl">D</span>
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">DarkTok</h1>
            <p className="text-xs text-mangaba-orange">by Mangaba.ai</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4">
        <ul className="space-y-2">
          {menuItems.map(item => (
            <li key={item.id}>
              <button
                onClick={() => setCurrentView(item.id)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                  currentView === item.id
                    ? 'bg-mangaba-orange text-white'
                    : 'text-gray-400 hover:bg-mangaba-orange/10 hover:text-white'
                }`}
              >
                <item.icon className="w-5 h-5" />
                <span className="font-medium">{item.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* Create Button */}
      <div className="p-4">
        <button className="w-full flex items-center justify-center gap-2 bg-mangaba-orange hover:bg-mangaba-orange-light text-white font-bold py-3 px-4 rounded-xl transition-all">
          <PlusSquare className="w-5 h-5" />
          <span>Criar</span>
        </button>
      </div>

      {/* Bottom Actions */}
      <div className="p-4 border-t border-mangaba-orange/20">
        <ul className="space-y-2">
          <li>
            <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-mangaba-orange/10 hover:text-white transition-all">
              <Settings className="w-5 h-5" />
              <span>Configurações</span>
            </button>
          </li>
          <li>
            <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-red-500/10 hover:text-red-500 transition-all">
              <LogOut className="w-5 h-5" />
              <span>Sair</span>
            </button>
          </li>
        </ul>
      </div>
    </aside>
  )
}
