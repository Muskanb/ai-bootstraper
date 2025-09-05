import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiService from '../services/api'

export const useSessionStore = defineStore('session', () => {
  // State
  const currentSession = ref(null)
  const sessionId = ref(null)
  const conversationHistory = ref([])
  const currentState = ref('INIT')
  const requirements = ref({
    project_type: null,
    language: null,
    framework: null,
    project_name: null,
    folder_path: null,
    database: null,
    authentication: false,
    testing: false,
    docker: false
  })
  const systemCapabilities = ref(null)
  const executionPlan = ref(null)
  const executionResults = ref([])
  const pendingQuestion = ref(null)
  const pendingPermission = ref(null)
  const waitingForUser = ref(false)
  const completionPercentage = ref(0)
  const errorMessage = ref(null)
  const isLoading = ref(false)

  // Computed
  const isSessionActive = computed(() => !!currentSession.value)
  const hasError = computed(() => !!errorMessage.value)
  const isComplete = computed(() => currentState.value === 'COMPLETED')
  const canExecute = computed(() => executionPlan.value && executionPlan.value.steps.length > 0)

  // Actions
  async function initializeSession() {
    try {
      isLoading.value = true
      errorMessage.value = null

      // Create new session
      const response = await apiService.createSession({
        metadata: {
          timestamp: new Date().toISOString(),
          user_agent: navigator.userAgent
        }
      })

      if (response.success) {
        sessionId.value = response.data.session_id
        currentState.value = response.data.state
        await loadSessionData()
      } else {
        throw new Error(response.error || 'Failed to create session')
      }
    } catch (error) {
      console.error('Failed to initialize session:', error)
      errorMessage.value = error.message
    } finally {
      isLoading.value = false
    }
  }

  async function loadSessionData() {
    if (!sessionId.value) return

    try {
      const response = await apiService.getSession(sessionId.value)
      
      if (response.success) {
        currentSession.value = response.data.session
        updateFromSessionState(response.data.session)
      }
    } catch (error) {
      console.error('Failed to load session:', error)
      errorMessage.value = error.message
    }
  }

  function updateFromSessionState(sessionState) {
    if (!sessionState) return

    currentState.value = sessionState.current_state
    requirements.value = { ...requirements.value, ...sessionState.requirements }
    systemCapabilities.value = sessionState.capabilities
    executionPlan.value = sessionState.execution_plan
    executionResults.value = sessionState.execution_results || []
    conversationHistory.value = sessionState.conversation_history || []
    pendingQuestion.value = sessionState.pending_question
    waitingForUser.value = sessionState.waiting_for_user || false
    completionPercentage.value = sessionState.completion_percentage || 0
    errorMessage.value = sessionState.error_message

    // Handle pending permissions
    if (pendingQuestion.value && pendingQuestion.value.type === 'permission') {
      pendingPermission.value = pendingQuestion.value
    }
  }

  function addMessage(role, content, metadata = {}) {
    const message = {
      role,
      content,
      timestamp: new Date().toISOString(),
      ...metadata
    }
    
    conversationHistory.value.push(message)
  }

  function updateRequirement(field, value) {
    requirements.value[field] = value
  }

  function updateState(newState) {
    currentState.value = newState
  }

  function updateProgress(percentage) {
    completionPercentage.value = Math.max(0, Math.min(100, percentage))
  }

  function setPendingQuestion(question) {
    pendingQuestion.value = question
    waitingForUser.value = true
  }

  function clearPendingQuestion() {
    pendingQuestion.value = null
    waitingForUser.value = false
  }

  function clearConversationHistory() {
    conversationHistory.value = []
  }

  function cleanUpDuplicateMessages() {
    const cleaned = []
    const seen = new Set()
    
    for (const message of conversationHistory.value) {
      const content = message.content?.trim()
      if (!content) continue
      
      if (message.role === 'assistant') {
        // For assistant messages, check for duplicates/partials
        const isDuplicate = cleaned.some(existing => 
          existing.role === 'assistant' && 
          existing.content &&
          (
            existing.content.includes(content) ||
            content.includes(existing.content) ||
            existing.content === content
          )
        )
        
        if (!isDuplicate) {
          cleaned.push(message)
        } else {
          // Replace with longer version if this one is longer
          const duplicateIndex = cleaned.findIndex(existing => 
            existing.role === 'assistant' && 
            existing.content &&
            (
              existing.content.includes(content) ||
              content.includes(existing.content) ||
              existing.content === content
            )
          )
          
          if (duplicateIndex >= 0 && content.length > cleaned[duplicateIndex].content.length) {
            cleaned[duplicateIndex] = message
          }
        }
      } else {
        // For user messages, simple duplicate check
        const key = `${message.role}-${content}`
        if (!seen.has(key)) {
          seen.add(key)
          cleaned.push(message)
        }
      }
    }
    
    conversationHistory.value = cleaned
  }

  function approvePermission(permission) {
    if (pendingPermission.value) {
      addMessage('user', 'Permission approved')
      pendingPermission.value = null
      pendingQuestion.value = null
      waitingForUser.value = false
    }
  }

  function denyPermission(permission) {
    if (pendingPermission.value) {
      addMessage('user', 'Permission denied')
      pendingPermission.value = null
      pendingQuestion.value = null
      waitingForUser.value = false
    }
  }

  function setSystemCapabilities(capabilities) {
    systemCapabilities.value = capabilities
  }

  function setExecutionPlan(plan) {
    executionPlan.value = plan
  }

  function addExecutionResult(result) {
    executionResults.value.push(result)
  }

  function setError(message) {
    errorMessage.value = message
  }

  function clearError() {
    errorMessage.value = null
  }

  function resetSession() {
    currentSession.value = null
    sessionId.value = null
    conversationHistory.value = []
    currentState.value = 'INIT'
    requirements.value = {
      project_type: null,
      language: null,
      framework: null,
      project_name: null,
      folder_path: null,
      database: null,
      authentication: false,
      testing: false,
      docker: false
    }
    systemCapabilities.value = null
    executionPlan.value = null
    executionResults.value = []
    pendingQuestion.value = null
    pendingPermission.value = null
    waitingForUser.value = false
    completionPercentage.value = 0
    errorMessage.value = null
    isLoading.value = false
  }

  // Save session state to backend
  async function saveSession() {
    if (!sessionId.value) return

    try {
      await apiService.updateSessionState(sessionId.value, {
        current_state: currentState.value,
        requirements: requirements.value,
        completion_percentage: completionPercentage.value,
        conversation_history: conversationHistory.value
      })
    } catch (error) {
      console.error('Failed to save session:', error)
    }
  }

  return {
    // State
    currentSession,
    sessionId,
    conversationHistory,
    currentState,
    requirements,
    systemCapabilities,
    executionPlan,
    executionResults,
    pendingQuestion,
    pendingPermission,
    waitingForUser,
    completionPercentage,
    errorMessage,
    isLoading,

    // Computed
    isSessionActive,
    hasError,
    isComplete,
    canExecute,

    // Actions
    initializeSession,
    loadSessionData,
    updateFromSessionState,
    addMessage,
    updateRequirement,
    updateState,
    updateProgress,
    setPendingQuestion,
    clearPendingQuestion,
    clearConversationHistory,
    cleanUpDuplicateMessages,
    approvePermission,
    denyPermission,
    setSystemCapabilities,
    setExecutionPlan,
    addExecutionResult,
    setError,
    clearError,
    resetSession,
    saveSession
  }
})