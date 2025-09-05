<template>
  <div class="min-h-screen bg-gray-50">
    <!-- Header -->
    <header class="bg-white shadow-sm border-b">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between items-center h-16">
          <div class="flex items-center">
            <h1 class="text-xl font-semibold text-gray-900">
              🤖 AI Agent Bootstrapper
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
            
            <!-- Session Info -->
            <div v-if="sessionStore.currentSession" class="text-sm text-gray-600">
              Session: {{ sessionStore.currentSession.session_id.slice(0, 8) }}...
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <ChatInterface />
    </main>

    <!-- Modals -->
    <PermissionModal 
      v-if="sessionStore.pendingPermission"
      :permission="sessionStore.pendingPermission"
      @approve="handlePermissionApproval"
      @deny="handlePermissionDenial"
    />
    
    <!-- Error Toast -->
    <div 
      v-if="sessionStore.hasError"
      class="fixed bottom-4 right-4 bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded max-w-sm"
    >
      <div class="flex justify-between items-start">
        <div>
          <strong class="font-bold">Error!</strong>
          <p class="text-sm">{{ sessionStore.errorMessage }}</p>
        </div>
        <button 
          @click="sessionStore.clearError"
          class="text-red-700 hover:text-red-900"
        >
          ×
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, computed } from 'vue'
import ChatInterface from '../components/ChatInterface.vue'
import PermissionModal from '../components/PermissionModal.vue'
import { useSessionStore } from '../stores/session'
import { useWebSocketStore } from '../stores/websocket'

const sessionStore = useSessionStore()
const wsStore = useWebSocketStore()

const connectionStatus = computed(() => wsStore.connectionStatus)

// Initialize application
onMounted(async () => {
  console.log('AI Agent Bootstrapper started')
  
  // Initialize session
  await sessionStore.initializeSession()
  
  // Connect WebSocket
  await wsStore.connect(sessionStore.sessionId)
})

// Cleanup on unmount
onUnmounted(() => {
  wsStore.disconnect()
})

// Handle permission approval
function handlePermissionApproval(permission) {
  sessionStore.approvePermission(permission)
  wsStore.sendMessage({
    type: 'user_message',
    data: { message: 'yes' }
  })
}

// Handle permission denial
function handlePermissionDenial(permission) {
  sessionStore.denyPermission(permission)
  wsStore.sendMessage({
    type: 'user_message',
    data: { message: 'no' }
  })
}
</script>