import { useState, useRef, useEffect } from 'react'
import { Heart, MessageCircle, Share2, Bookmark, Play, Pause, Volume2, VolumeX } from 'lucide-react'

interface Video {
  id: string
  url: string
  thumbnail: string
  username: string
  description: string
  likes: number
  comments: number
  shares: number
  song: string
  isLiked: boolean
  isSaved: boolean
}

const mockVideos: Video[] = [
  {
    id: '1',
    url: '',
    thumbnail: 'https://images.unsplash.com/photo-1536440136628-849c177e76a1?w=800',
    username: '@cinemaai',
    description: 'A arte do cinema através da IA 🎬✨',
    likes: 45200,
    comments: 1230,
    shares: 890,
    song: 'Original Sound - CinemaAI',
    isLiked: false,
    isSaved: false,
  },
  {
    id: '2',
    url: '',
    thumbnail: 'https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=800',
    username: '@techvibes',
    description: 'O futuro é agora 🚀 #tecnologia #futuro',
    likes: 23400,
    comments: 567,
    shares: 234,
    song: 'Synthwave Mix - TechVibes',
    isLiked: true,
    isSaved: false,
  },
  {
    id: '3',
    url: '',
    thumbnail: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800',
    username: '@artdig',
    description: 'Arte digital criada com IA 🎨',
    likes: 67800,
    comments: 2340,
    shares: 1560,
    song: 'Digital Dreams - ArtDig',
    isLiked: false,
    isSaved: true,
  },
  {
    id: '4',
    url: '',
    thumbnail: 'https://images.unsplash.com/photo-1518770660439-4636190af475?w=800',
    username: '@codeflow',
    description: 'Programando o amanhã 💻 #coding #ia',
    likes: 34500,
    comments: 890,
    shares: 456,
    song: 'Code Beat - CodeFlow',
    isLiked: false,
    isSaved: false,
  },
  {
    id: '5',
    url: '',
    thumbnail: 'https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=800',
    username: '@robotfuture',
    description: 'Robôs e IA transformando o mundo 🤖',
    likes: 89100,
    comments: 3450,
    shares: 2340,
    song: 'Robot Dance - FutureAI',
    isLiked: true,
    isSaved: true,
  },
]

export default function VideoFeed() {
  const [currentIndex, setCurrentIndex] = useState(0)
  const [videos, setVideos] = useState(mockVideos)
  const containerRef = useRef<HTMLDivElement>(null)

  const handleScroll = () => {
    if (containerRef.current) {
      const scrollTop = containerRef.current.scrollTop
      const itemHeight = containerRef.current.clientHeight
      const newIndex = Math.round(scrollTop / itemHeight)
      if (newIndex !== currentIndex) {
        setCurrentIndex(newIndex)
      }
    }
  }

  const toggleLike = (id: string) => {
    setVideos(prev => prev.map(video => 
      video.id === id ? { ...video, isLiked: !video.isLiked } : video
    ))
  }

  const toggleSave = (id: string) => {
    setVideos(prev => prev.map(video => 
      video.id === id ? { ...video, isSaved: !video.isSaved } : video
    ))
  }

  const formatNumber = (num: number) => {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
    return num.toString()
  }

  return (
    <div 
      ref={containerRef}
      onScroll={handleScroll}
      className="video-container h-full"
    >
      {videos.map((video, index) => (
        <div 
          key={video.id}
          className="video-item flex items-center justify-center bg-black"
        >
          {/* Background Image */}
          <div 
            className="absolute inset-0 bg-cover bg-center"
            style={{ backgroundImage: `url(${video.thumbnail})` }}
          >
            <div className="absolute inset-0 bg-black/30" />
          </div>

          {/* Play Button Overlay */}
          <div className="absolute inset-0 flex items-center justify-center">
            <button className="w-20 h-20 bg-white/20 backdrop-blur-sm rounded-full flex items-center justify-center hover:bg-white/30 transition-all">
              <Play className="w-10 h-10 text-white ml-1" fill="white" />
            </button>
          </div>

          {/* Bottom Info */}
          <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black/80 to-transparent">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-white font-bold">{video.username}</span>
            </div>
            <p className="text-white text-sm mb-2">{video.description}</p>
            <div className="flex items-center gap-2 text-xs text-white/70">
              <span>🎵</span>
              <span className="truncate">{video.song}</span>
            </div>
          </div>

          {/* Right Sidebar - Actions */}
          <div className="absolute right-4 bottom-24 flex flex-col items-center gap-6">
            {/* Like */}
            <button 
              onClick={() => toggleLike(video.id)}
              className="flex flex-col items-center"
            >
              <div className={`p-3 rounded-full ${video.isLiked ? 'bg-mangaba-orange' : 'bg-white/10 backdrop-blur-sm'} transition-all`}>
                <Heart 
                  className={`w-7 h-7 ${video.isLiked ? 'text-white fill-white' : 'text-white'} ${video.isLiked ? 'like-animation' : ''}`} 
                />
              </div>
              <span className="text-white text-xs mt-1">{formatNumber(video.likes)}</span>
            </button>

            {/* Comments */}
            <button className="flex flex-col items-center">
              <div className="p-3 rounded-full bg-white/10 backdrop-blur-sm">
                <MessageCircle className="w-7 h-7 text-white" />
              </div>
              <span className="text-white text-xs mt-1">{formatNumber(video.comments)}</span>
            </button>

            {/* Share */}
            <button className="flex flex-col items-center">
              <div className="p-3 rounded-full bg-white/10 backdrop-blur-sm">
                <Share2 className="w-7 h-7 text-white" />
              </div>
              <span className="text-white text-xs mt-1">{formatNumber(video.shares)}</span>
            </button>

            {/* Save */}
            <button 
              onClick={() => toggleSave(video.id)}
              className="flex flex-col items-center"
            >
              <div className={`p-3 rounded-full ${video.isSaved ? 'bg-mangaba-orange' : 'bg-white/10 backdrop-blur-sm'} transition-all`}>
                <Bookmark 
                  className={`w-7 h-7 ${video.isSaved ? 'text-white fill-white' : 'text-white'}`} 
                />
              </div>
            </button>

            {/* Profile Picture */}
            <div className="w-12 h-12 rounded-full border-2 border-mangaba-orange overflow-hidden">
              <img 
                src={video.thumbnail} 
                alt={video.username}
                className="w-full h-full object-cover"
              />
            </div>
          </div>

          {/* Progress Bar */}
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20">
            <div 
              className="h-full bg-mangaba-orange transition-all duration-300"
              style={{ width: `${((index + 1) / videos.length) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}
