import { useState } from 'react'
import VideoFeed from './components/VideoFeed'
import Sidebar from './components/Sidebar'
import Header from './components/Header'

function App() {
  const [currentView, setCurrentView] = useState<'feed' | 'explore' | 'notifications' | 'profile'>('feed')

  return (
    <div className="flex h-screen bg-mangaba-dark">
      <Sidebar currentView={currentView} setCurrentView={setCurrentView} />
      
      <main className="flex-1 flex flex-col">
        <Header currentView={currentView} />
        
        <div className="flex-1 overflow-hidden">
          {currentView === 'feed' && <VideoFeed />}
          {currentView === 'explore' && <Explore />}
          {currentView === 'notifications' && <Notifications />}
          {currentView === 'profile' && <Profile />}
        </div>
      </main>
    </div>
  )
}

function Explore() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <div className="text-6xl mb-4">🔍</div>
        <h2 className="text-2xl font-bold text-mangaba-orange mb-2">Explorar</h2>
        <p className="text-mangaba-text-muted">Descubra novos conteúdos</p>
      </div>
    </div>
  )
}

function Notifications() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <div className="text-6xl mb-4">🔔</div>
        <h2 className="text-2xl font-bold text-mangaba-orange mb-2">Notificações</h2>
        <p className="text-mangaba-text-muted">Suas atividades recentes</p>
      </div>
    </div>
  )
}

function Profile() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <div className="text-6xl mb-4">👤</div>
        <h2 className="text-2xl font-bold text-mangaba-orange mb-2">Perfil</h2>
        <p className="text-mangaba-text-muted">Seu perfil no DarkTok</p>
      </div>
    </div>
  )
}

export default App
