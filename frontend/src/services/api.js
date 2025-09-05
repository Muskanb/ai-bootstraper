import axios from 'axios'

// Create axios instance with base configuration
const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor for logging
apiClient.interceptors.request.use(
  (config) => {
    console.log(`API Request: ${config.method.toUpperCase()} ${config.url}`)
    return config
  },
  (error) => {
    console.error('API Request Error:', error)
    return Promise.reject(error)
  }
)

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => {
    console.log(`API Response: ${response.status} ${response.config.url}`)
    return response.data // Return just the data
  },
  (error) => {
    console.error('API Response Error:', error)
    
    // Handle different error types
    if (error.response) {
      // Server responded with error status
      const errorMessage = error.response.data?.detail || error.response.data?.error || error.message
      return Promise.reject(new Error(errorMessage))
    } else if (error.request) {
      // Request was made but no response received
      return Promise.reject(new Error('No response from server'))
    } else {
      // Something happened in setting up the request
      return Promise.reject(new Error(error.message))
    }
  }
)

// API Service
const apiService = {
  // Session Management
  async createSession(data = {}) {
    return await apiClient.post('/sessions', data)
  },

  async getSession(sessionId) {
    return await apiClient.get(`/sessions/${sessionId}`)
  },

  async deleteSession(sessionId) {
    return await apiClient.delete(`/sessions/${sessionId}`)
  },

  async listSessions() {
    return await apiClient.get('/sessions')
  },

  async updateSessionState(sessionId, updates) {
    return await apiClient.post(`/sessions/${sessionId}/state`, updates)
  },

  // Conversation
  async sendMessage(sessionId, message, metadata = {}) {
    return await apiClient.post(`/sessions/${sessionId}/messages`, {
      session_id: sessionId,
      response: message,
      metadata
    })
  },

  async getConversationHistory(sessionId, limit = null) {
    const params = limit ? { limit } : {}
    return await apiClient.get(`/sessions/${sessionId}/history`, { params })
  },

  // Checkpoints
  async createCheckpoint(sessionId) {
    return await apiClient.post(`/sessions/${sessionId}/checkpoint`)
  },

  async restoreCheckpoint(sessionId, checkpointId) {
    return await apiClient.post(`/sessions/${sessionId}/restore`, {
      checkpoint_id: checkpointId
    })
  },

  // System
  async getHealth() {
    return await apiClient.get('/health')
  },

  async getStats() {
    return await apiClient.get('/stats')
  },

  async cleanupExpiredSessions() {
    return await apiClient.post('/cleanup')
  }
}

export default apiService