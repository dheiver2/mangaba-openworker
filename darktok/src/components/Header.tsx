import { Search, Bell, User } from 'lucide-react'

interface HeaderProps {
  currentView: 'feed' | 'explore' | 'notifications' | 'profile'
}

export default function Header({ currentView }: HeaderProps) {
  const getTitle = () => {
    switch (currentView) {
      case 'feed': return 'Para Você'
      case 'explore': return 'Explorar'
      case 'notifications': return 'Notificações'
      case 'profile': return 'Perfil'
    }
  }

  return (
    <header className="h-16 bg-mangaba-surface border-b border-mangaba-orange/20 flex items-center justify-between px-6">
      <div className="flex items-center gap-4">
        <h2 className="text-xl font-bold text-white">{getTitle()}</h2>
        {currentView === 'feed' && (
          <div className="flex gap-2">
            <button className="px-4 py-1.5 bg-mangaba-orange text-white rounded-full text-sm font-medium">
              Seguindo
            </button>
            <button className="px-4 py-1.5 text-gray-400 hover:text-white rounded-full text-sm font-medium transition-colors">
              Para Você
            </button>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4">
        {/* Search */}
        <div className="relative">
          <input
            type="text"
            placeholder="Pesquisar..."
            className="w-64 bg-mangaba-dark border border-mangaba-orange/20 rounded-full px-4 py-2 pl-10 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-mangaba-orange transition-colors"
          />
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
        </div>

        {/* Notifications */}
        <button className="relative p-2 text-gray-400 hover:text-white transition-colors">
          <Bell className="w-5 h-5" />
          <span className="absolute top-1 right-1 w-2 h-2 bg-mangaba-orange rounded-full" />
        </button>

        {/* Profile */}
        <button className="w-8 h-8 rounded-full bg-mangaba-orange flex items-center justify-center">
          <User className="w-4 h-4 text-white" />
        </button>
      </div>
    </header>
  )
}
