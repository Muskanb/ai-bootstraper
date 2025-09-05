<template>
  <div class="min-h-screen bg-gray-50">
    <!-- Header -->
    <header class="bg-white shadow-sm border-b">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between items-center h-16">
          <div class="flex items-center">
            <router-link to="/" class="mr-4 text-gray-500 hover:text-gray-700">
              ← Back
            </router-link>
            <h1 class="text-xl font-semibold text-gray-900">
              🤖 Session: {{ $route.params.sessionId.slice(0, 8) }}...
            </h1>
          </div>
          
          <div class="flex items-center space-x-4">
            <!-- Connection Status -->
            <div class="flex items-center">
              <div 
                :class="connectionStatus === 'connected' ? 'bg-green-400' : 'bg-red-400'"
                class="w-2 h-2 rounded-full mr-2"
              ></div>
              <span class="text-sm text-gray-600">
                {{ connectionStatus === 'connected' ? 'Connected' : 'Disconnected' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <ChatInterface />
    </main>
  </div>
</template>

<script>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { useWebSocketStore } from '../stores/websocket'
import ChatInterface from '../components/ChatInterface.vue'

export default {
  name: 'Session',
  components: {
    ChatInterface
  },
  setup() {
    const route = useRoute()
    const sessionStore = useSessionStore()
    const wsStore = useWebSocketStore()
    
    const connectionStatus = computed(() => {
      return wsStore.connectionState === 'connected' ? 'connected' : 'disconnected'
    })
    
    onMounted(async () => {
      const sessionId = route.params.sessionId
      
      // Load session if not already loaded
      if (!sessionStore.currentSession || sessionStore.currentSession.session_id !== sessionId) {
        await sessionStore.loadSession(sessionId)
      }
      
      // Connect WebSocket for this session
      wsStore.connect(sessionId)
    })
    
    return {
      connectionStatus
    }
  }
}
</script>