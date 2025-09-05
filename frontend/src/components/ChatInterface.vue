<template>
  <div class="card h-[600px] flex flex-col">
    <div class="card-header flex justify-between items-center">
      <div>
        <h2 class="text-lg font-semibold text-gray-900">Conversation</h2>
        <p class="text-sm text-gray-600 mt-1">
          Chat with the AI agent to create your project
        </p>
      </div>
      <div class="flex items-center space-x-2">
        <button @click="cleanupDuplicates" class="text-sm text-gray-500 hover:text-gray-700" title="Clean up duplicates">
          🧹
        </button>
        <button @click="clearHistory" class="text-sm text-gray-500 hover:text-gray-700" title="Clear conversation">
          🗑️
        </button>
        <span class="text-xs text-gray-400">{{ filteredMessages.length }} messages</span>
      </div>
    </div>

    <!-- Messages -->
    <div 
      ref="messagesContainer"
      class="flex-1 overflow-y-auto space-y-3 mb-4 scrollable p-1"
    >
      <div 
        v-for="(message, index) in filteredMessages" 
        :key="message.id || `${message.role}-${index}-${message.timestamp}`"
        class="fade-in"
      >
        <!-- User Message -->
        <div v-if="message.role === 'user'" class="flex justify-end group">
          <div class="message-user relative max-w-[80%]">
            <p class="whitespace-pre-wrap break-words">{{ message.content }}</p>
            <span class="text-xs opacity-75 block mt-1">
              {{ formatTime(message.timestamp) }}
            </span>
            <button 
              @click="copyMessage(message.content)"
              class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-gray-600"
              title="Copy message"
            >
              📋
            </button>
          </div>
        </div>

        <!-- Assistant Message -->
        <div v-else-if="message.role === 'assistant'" class="flex justify-start group">
          <div class="message-assistant relative max-w-[85%]">
            <div class="flex items-start space-x-2">
              <div class="w-7 h-7 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0">
                <span class="text-sm">🤖</span>
              </div>
              <div class="flex-1 min-w-0">
                <div class="prose prose-sm max-w-none">
                  <p class="whitespace-pre-wrap break-words m-0">
                    <TypewriterText 
                      :text="message.content" 
                      :is-streaming="message.streaming"
                      :typing-speed="typingSpeed"
                    />
                  </p>
                </div>
                <div v-if="message.streaming" class="flex items-center mt-2">
                  <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                  <span class="text-xs text-gray-500 ml-2">AI is typing...</span>
                </div>
                <span class="text-xs text-gray-500 block mt-1">
                  {{ formatTime(message.timestamp) }}
                </span>
              </div>
            </div>
            <button 
              @click="copyMessage(message.content)"
              class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-gray-600"
              title="Copy message"
            >
              📋
            </button>
          </div>
        </div>

        <!-- System Message -->
        <div v-else-if="message.role === 'system'" class="flex justify-center">
          <div class="message-system">
            <p class="text-center">{{ message.content }}</p>
          </div>
        </div>
      </div>

      <!-- Processing/Typing Indicator -->
      <div v-if="isAiTyping || wsStore.isProcessingAIMessage" class="flex justify-start fade-in">
        <div class="message-assistant">
          <div class="flex items-center space-x-2">
            <div class="w-7 h-7 bg-blue-100 rounded-full flex items-center justify-center">
              <span class="text-sm">🤖</span>
            </div>
            <div class="flex items-center">
              <div class="typing-indicator mr-3">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <span class="text-sm text-gray-500">
                {{ wsStore.isProcessingAIMessage ? 'Processing message...' : 'AI is thinking...' }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="filteredMessages.length === 0" class="text-center py-12">
        <div class="text-gray-400 mb-4">
          <svg class="w-20 h-20 mx-auto" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clip-rule="evenodd"></path>
          </svg>
        </div>
        <h3 class="text-lg font-medium text-gray-700 mb-2">Ready to start!</h3>
        <p class="text-gray-500 mb-4">Tell me about the project you'd like to create</p>
        <div class="flex flex-wrap justify-center gap-2 max-w-md mx-auto">
          <button @click="startConversation('Web App')" class="btn-outline text-sm">Web App</button>
          <button @click="startConversation('API Server')" class="btn-outline text-sm">API Server</button>
          <button @click="startConversation('CLI Tool')" class="btn-outline text-sm">CLI Tool</button>
          <button @click="startConversation('React App')" class="btn-outline text-sm">React App</button>
        </div>
      </div>
    </div>

    <!-- Pending Question -->
    <div v-if="pendingQuestion && pendingQuestion.type === 'choice'" class="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
      <p class="text-sm font-medium text-blue-900 mb-3">{{ pendingQuestion.question }}</p>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="option in pendingQuestion.options"
          :key="option"
          @click="selectOption(option)"
          class="btn-secondary text-sm"
        >
          {{ option }}
        </button>
      </div>
    </div>

    <!-- Input Area -->
    <div class="border-t pt-4">
      <!-- Completion State -->
      <div v-if="isComplete" class="text-center py-4">
        <div class="mb-4">
          <div class="text-lg font-semibold text-green-600 mb-2">
            ✅ Project Completed!
          </div>
          <p class="text-gray-600 text-sm">
            Your project has been successfully created and configured.
          </p>
        </div>
        <button
          @click="restartSession"
          class="btn-primary"
        >
          🔄 Start New Project
        </button>
      </div>
      
      <!-- Normal Chat Input -->
      <div v-else>
        <form @submit.prevent="sendMessage" class="flex space-x-2">
          <input
            v-model="currentMessage"
            :disabled="waitingForUser || isLoading"
            :placeholder="getInputPlaceholder()"
            class="input-field flex-1"
            @keyup.enter="sendMessage"
          />
          <button
            type="submit"
            :disabled="!canSendMessage"
            class="btn-primary"
          >
            <span v-if="isLoading" class="flex items-center">
              <div class="loading-spinner mr-2"></div>
              Sending...
            </span>
            <span v-else>Send</span>
          </button>
        </form>
        
        <div class="flex justify-between items-center mt-2 text-xs text-gray-500">
          <span>{{ currentState }}</span>
          <span v-if="completionPercentage > 0">{{ completionPercentage }}% complete</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { useSessionStore } from '../stores/session'
import { useWebSocketStore } from '../stores/websocket'
import TypewriterText from './TypewriterText.vue'

const sessionStore = useSessionStore()
const wsStore = useWebSocketStore()

// Local state
const currentMessage = ref('')
const messagesContainer = ref(null)
const isAiTyping = ref(false)
const typingSpeed = ref(30) // milliseconds per character

// Computed properties
const conversationHistory = computed(() => sessionStore.conversationHistory)
const pendingQuestion = computed(() => sessionStore.pendingQuestion)
const waitingForUser = computed(() => sessionStore.waitingForUser)
const isLoading = computed(() => sessionStore.isLoading || wsStore.isConnecting)
const currentState = computed(() => sessionStore.currentState)
const completionPercentage = computed(() => Math.round(sessionStore.completionPercentage))
const isComplete = computed(() => sessionStore.isComplete)

// Clean message filtering - most duplicate prevention now handled in WebSocket store
const filteredMessages = computed(() => {
  return conversationHistory.value.filter(message => {
    // Skip empty messages
    const content = message.content?.trim()
    if (!content) return false
    
    // Skip session metadata messages
    if (content.startsWith('Session metadata:') || 
        content.includes('"timestamp":') && content.includes('"user_agent":')) {
      return false
    }
    
    // All messages should be clean now due to aggressive backend filtering
    return true
  })
})

const canSendMessage = computed(() => {
  return !isLoading.value && 
         !waitingForUser.value && 
         currentMessage.value.trim().length > 0 &&
         wsStore.isConnected
})

// Watch for new messages and scroll to bottom
watch(filteredMessages, async () => {
  await nextTick()
  scrollToBottom()
}, { deep: true })

// Watch for WebSocket messages to detect AI typing
watch(() => wsStore.lastMessage, (newMessage) => {
  if (newMessage) {
    if (newMessage.type === 'ai_message_chunk') {
      isAiTyping.value = true
    } else if (newMessage.type === 'ai_message' || newMessage.type === 'function_execution_complete') {
      isAiTyping.value = false
    }
  }
})

// Methods
function sendMessage() {
  if (!canSendMessage.value) return

  const message = currentMessage.value.trim()
  if (!message) return

  // Add user message to history
  sessionStore.addMessage('user', message)
  
  // Send via WebSocket
  wsStore.sendUserMessage(message)
  
  // Clear input
  currentMessage.value = ''
  
  // Scroll to bottom
  scrollToBottom()
}

function selectOption(option) {
  if (pendingQuestion.value && pendingQuestion.value.field) {
    // Update requirement
    sessionStore.updateRequirement(pendingQuestion.value.field, option)
  }
  
  // Send selected option as message
  currentMessage.value = option
  sendMessage()
  
  // Clear pending question
  sessionStore.clearPendingQuestion()
}

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  
  const date = new Date(timestamp)
  return date.toLocaleTimeString([], { 
    hour: '2-digit', 
    minute: '2-digit' 
  })
}

function getInputPlaceholder() {
  if (waitingForUser.value) {
    return 'Please respond to the question above...'
  } else if (isLoading.value) {
    return 'Processing...'
  } else if (!wsStore.isConnected) {
    return 'Connecting to server...'
  } else {
    return 'Type your message here...'
  }
}

function clearHistory() {
  if (confirm('Are you sure you want to clear the conversation history?')) {
    sessionStore.clearConversationHistory()
  }
}

function cleanupDuplicates() {
  sessionStore.cleanUpDuplicateMessages()
}

function copyMessage(content) {
  navigator.clipboard.writeText(content).then(() => {
    // You could add a toast notification here
    console.log('Message copied to clipboard')
  })
}

function startConversation(projectType) {
  currentMessage.value = `I want to create a ${projectType}`
  sendMessage()
}

function restartSession() {
  // Clear current session and start fresh
  sessionStore.clearSession()
  wsStore.disconnect()
  
  // Reload the page to start fresh
  window.location.reload()
}

// Auto-start conversation if session is new
watch(() => sessionStore.currentState, (newState) => {
  if (newState === 'INIT' && filteredMessages.value.length === 0) {
    // Send initial start message
    setTimeout(() => {
      wsStore.sendMessage({
        type: 'start_new_session'
      })
    }, 1000)
  }
})
</script>

<style scoped>
/* Component-specific styles */
.scrollable {
  scrollbar-width: thin;
  scrollbar-color: rgb(209 213 219) rgb(243 244 246);
}

.scrollable::-webkit-scrollbar {
  width: 8px;
}

.scrollable::-webkit-scrollbar-track {
  background: rgb(243 244 246);
  border-radius: 4px;
}

.scrollable::-webkit-scrollbar-thumb {
  background: rgb(209 213 219);
  border-radius: 4px;
}

.scrollable::-webkit-scrollbar-thumb:hover {
  background: rgb(156 163 175);
}

/* Enhanced message styling */
.message-user {
  @apply bg-blue-600 text-white rounded-2xl px-4 py-2.5 shadow-sm;
  border-bottom-right-radius: 8px;
}

.message-assistant {
  @apply bg-gray-50 text-gray-900 rounded-2xl px-4 py-3 shadow-sm border border-gray-100;
  border-bottom-left-radius: 8px;
}

.message-system {
  @apply bg-yellow-50 text-yellow-800 rounded-lg px-3 py-2 text-sm border border-yellow-200;
}

/* Smooth animations */
.fade-in {
  animation: fadeIn 0.3s ease-in-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Loading spinner improvements */
.loading-spinner {
  @apply w-4 h-4 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin;
}

/* Typing indicator animation */
.typing-indicator {
  display: flex;
  gap: 2px;
  align-items: center;
}

.typing-indicator span {
  width: 4px;
  height: 4px;
  background-color: #9CA3AF;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) {
  animation-delay: -0.32s;
}

.typing-indicator span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes typing {
  0%, 80%, 100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  40% {
    opacity: 1;
    transform: scale(1);
  }
}

/* Hover effects for buttons */
.btn-outline {
  @apply px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors duration-200;
}

/* Prose styling for better text formatting */
.prose {
  color: inherit;
}

.prose p {
  margin-bottom: 0.75rem;
}

.prose p:last-child {
  margin-bottom: 0;
}
</style>