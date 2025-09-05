import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSessionStore } from './session'

export const useWebSocketStore = defineStore('websocket', () => {
  // State
  const socket = ref(null)
  const connectionStatus = ref('disconnected') // 'disconnected', 'connecting', 'connected', 'error'
  const lastMessage = ref(null)
  const messageQueue = ref([])
  const reconnectAttempts = ref(0)
  const maxReconnectAttempts = ref(5)
  const reconnectInterval = ref(null)
  const heartbeatInterval = ref(null)
  
  const isProcessingAIMessage = ref(false)

  // Computed
  const isConnected = computed(() => connectionStatus.value === 'connected')
  const isConnecting = computed(() => connectionStatus.value === 'connecting')
  const shouldReconnect = computed(() => reconnectAttempts.value < maxReconnectAttempts.value)

  // Actions
  async function connect(sessionId) {
    if (socket.value && socket.value.readyState === WebSocket.OPEN) {
      console.log('WebSocket already connected')
      return
    }

    try {
      connectionStatus.value = 'connecting'
      console.log(`Connecting to WebSocket: ws://localhost:8000/ws/${sessionId}`)
      
      socket.value = new WebSocket(`ws://localhost:8000/ws/${sessionId}`)
      
      socket.value.onopen = handleOpen
      socket.value.onmessage = handleMessage
      socket.value.onclose = handleClose
      socket.value.onerror = handleError
      
    } catch (error) {
      console.error('Failed to connect WebSocket:', error)
      connectionStatus.value = 'error'
      scheduleReconnect()
    }
  }

  function disconnect() {
    if (socket.value) {
      socket.value.close()
      socket.value = null
    }
    
    clearInterval(heartbeatInterval.value)
    clearInterval(reconnectInterval.value)
    
    connectionStatus.value = 'disconnected'
    reconnectAttempts.value = 0
  }

  function sendMessage(message) {
    if (!isConnected.value) {
      console.warn('WebSocket not connected, queueing message:', message)
      messageQueue.value.push(message)
      return
    }

    try {
      const messageStr = JSON.stringify({
        ...message,
        timestamp: new Date().toISOString()
      })
      
      socket.value.send(messageStr)
      console.log('Sent message:', message.type)
      
    } catch (error) {
      console.error('Failed to send message:', error)
      messageQueue.value.push(message)
    }
  }

  function sendUserMessage(content) {
    sendMessage({
      type: 'user_message',
      data: { message: content }
    })
  }

  function requestSessionState() {
    sendMessage({
      type: 'get_session_state'
    })
  }

  function sendHeartbeat() {
    sendMessage({
      type: 'heartbeat'
    })
  }

  // Final AI Message Handler - Complete streaming message or add new one
  function handleFinalAIMessage(data) {
    const messageContent = data.message?.trim()
    if (!messageContent) return
    
    const sessionStore = useSessionStore()
    const history = sessionStore.conversationHistory
    
    // Check if there's an active streaming message to complete
    const lastMessage = history[history.length - 1]
    
    if (lastMessage && lastMessage.role === 'assistant' && lastMessage.streaming) {
      // Complete the streaming message
      lastMessage.content = messageContent
      lastMessage.streaming = false
      delete lastMessage.isStreamingMessage
      delete lastMessage.id
    } else {
      // Add new message if no streaming message exists
      sessionStore.addMessage('assistant', messageContent)
    }
    
    // Clear any processing indicator
    isProcessingAIMessage.value = false
    
    // Update state if provided
    if (data.state) {
      sessionStore.updateState(data.state)
    }
  }

  // Event Handlers
  function handleOpen(event) {
    console.log('WebSocket connected')
    connectionStatus.value = 'connected'
    reconnectAttempts.value = 0
    
    // Send queued messages
    while (messageQueue.value.length > 0) {
      const message = messageQueue.value.shift()
      sendMessage(message)
    }
    
    // Start heartbeat
    startHeartbeat()
  }

  function handleMessage(event) {
    try {
      const message = JSON.parse(event.data)
      lastMessage.value = message
      
      console.log('📨 WebSocket Received message:', message.type, message.data)
      
      // Handle different message types
      processMessage(message)
      
    } catch (error) {
      console.error('Failed to parse WebSocket message:', error)
    }
  }

  function handleClose(event) {
    console.log('WebSocket closed:', event.code, event.reason)
    connectionStatus.value = 'disconnected'
    
    clearInterval(heartbeatInterval.value)
    
    // Schedule reconnect if not a clean close
    if (event.code !== 1000 && shouldReconnect.value) {
      scheduleReconnect()
    }
  }

  function handleError(error) {
    console.error('WebSocket error:', error)
    connectionStatus.value = 'error'
    
    // Try to reconnect
    if (shouldReconnect.value) {
      scheduleReconnect()
    }
  }

  // Message Processing
  function processMessage(message) {
    const sessionStore = useSessionStore()
    
    switch (message.type) {
      case 'connection_established':
        console.log('Connection established:', message.data)
        break
        
      case 'ai_message':
        // Handle AI message with final-message-only approach
        handleFinalAIMessage(message.data)
        break
        
      case 'ai_message_chunk':
        // Handle streaming chunks for real-time display
        handleStreamingChunk(message.data)
        break
        
      case 'function_call_detected':
        console.log('Function call detected:', message.data)
        break
        
      case 'function_execution_start':
        const sessionStore = useSessionStore()
        if (message.data.name === 'detect_system_capabilities') {
          sessionStore.addMessage('system', '🔍 Detecting system capabilities and installed tools...')
        } else if (message.data.name === 'request_permission') {
          sessionStore.addMessage('system', '🔒 Requesting user permissions...')
        } else {
          sessionStore.addMessage('system', `⚙️ Executing: ${message.data.name}...`)
        }
        break
        
      case 'function_execution_complete':
        const sessionStore2 = useSessionStore()
        if (message.data.name === 'detect_system_capabilities') {
          const result = message.data.result
          if (result.status === 'capabilities_detected') {
            const caps = result.capabilities
            sessionStore2.addMessage('system', `✅ System scan complete! Found: ${caps.os}, Python ${caps.python_version || 'not found'}, Node.js ${caps.node_version || 'not found'}`)
          } else {
            sessionStore2.addMessage('system', '❌ System capability detection failed')
          }
        } else if (message.data.name === 'create_project_with_steps') {
          const result = message.data.result
          if (result.status === 'execution_completed') {
            sessionStore2.addMessage('system', `✅ Project creation completed! Created ${result.project_name || 'project'} at ${result.project_path || './project'}`)
          }
        }
        break
        
      case 'function_execution_error':
        console.error('Function execution error:', message.data.error)
        sessionStore.setError(message.data.error)
        break
        
      case 'state_update':
        if (message.data.session_state) {
          sessionStore.updateFromSessionState(message.data.session_state)
        }
        if (message.data.updates) {
          processStateUpdates(message.data.updates)
        }
        break
        
      case 'session_resumed':
        console.log('Session resumed')
        if (message.data.conversation_history) {
          sessionStore.conversationHistory = message.data.conversation_history
        }
        if (message.data.progress) {
          sessionStore.updateProgress(message.data.progress.progress_percentage)
        }
        break
        
      case 'command_start':
        console.log('Command started:', message.data.command)
        break
        
      case 'command_output':
        handleCommandOutput(message.data)
        break
        
      case 'command_complete':
        console.log('Command completed:', message.data.success)
        break
        
      case 'command_error':
        console.error('Command error:', message.data.error)
        break
        
      case 'progress_update':
        sessionStore.updateProgress(message.data.percentage)
        break
        
      case 'error':
        sessionStore.setError(message.data.message)
        break
        
      case 'warning':
        console.warn('Warning:', message.data.message)
        break
        
      case 'info':
        console.info('Info:', message.data.message)
        break
        
      case 'success':
        console.log('Success:', message.data.message)
        break
        
      case 'project_creation_success':
        const sessionStore3 = useSessionStore()
        const projectName = message.data.project_name || 'project'
        const projectPath = message.data.project_path || './project'
        const successfulSteps = message.data.successful_steps || 0
        const totalSteps = message.data.total_steps || 0
        sessionStore3.addMessage('system', `🎉 Project "${projectName}" created successfully! (${successfulSteps}/${totalSteps} steps completed)`)
        sessionStore3.addMessage('system', `📁 Project location: ${projectPath}`)
        sessionStore3.addMessage('system', '🔄 Session will close automatically in 15 seconds...')
        
        isProcessingAIMessage.value = false
        
        setTimeout(() => {
          exitSession()
        }, 15000)
        break
        
      case 'workflow_complete':
        const sessionStore4 = useSessionStore()
        sessionStore4.addMessage('system', '✅ Workflow completed successfully!')
        sessionStore4.addMessage('system', '🔄 Session will close automatically in 10 seconds...')
        
        isProcessingAIMessage.value = false
        
        setTimeout(() => {
          exitSession()
        }, 10000)
        break
        
      case 'capabilities_auto_detected':
        const sessionStore5 = useSessionStore()
        const capabilityMessage = message.data.message || '🔍 System capabilities detected automatically'
        sessionStore5.addMessage('system', capabilityMessage)
        break
        
      case 'technology_cleanup_start':
        const sessionStore6 = useSessionStore()
        sessionStore6.addMessage('system', message.data.message)
        break
        
      case 'technology_cleanup_progress':
        const sessionStore7 = useSessionStore()
        sessionStore7.addMessage('system', message.data.message)
        break
        
      case 'technology_cleanup_complete':
        console.log('✅ TECHNOLOGY_CLEANUP_COMPLETE received:', message.data)
        const sessionStore8 = useSessionStore()
        sessionStore8.addMessage('system', message.data.message)
        break
        
      case 'technology_cleanup_error':
        console.log('⚠️ TECHNOLOGY_CLEANUP_ERROR received:', message.data)
        const sessionStore9 = useSessionStore()
        sessionStore9.addMessage('system', message.data.message)
        break
        
      case 'session_recovery_status':
        console.log('🔧 SESSION_RECOVERY_STATUS received:', message.data)
        const sessionStore10 = useSessionStore()
        sessionStore10.addMessage('system', message.data.message)
        break
        
      case 'step_regeneration_notice':
        console.log('🔄 STEP_REGENERATION_NOTICE received:', message.data)
        const sessionStore11 = useSessionStore()
        sessionStore11.addMessage('system', message.data.message)
        if (message.data.note) {
          sessionStore11.addMessage('system', `📋 ${message.data.note}`)
        }
        break
        
      case 'steps_regenerated':
        console.log('✅ STEPS_REGENERATED received:', message.data)
        const sessionStore12 = useSessionStore()
        sessionStore12.addMessage('system', message.data.message)
        break
        
      case 'step_regeneration_failed':
        console.log('⚠️ STEP_REGENERATION_FAILED received:', message.data)
        const sessionStore13 = useSessionStore()
        sessionStore13.addMessage('system', message.data.message)
        break
        
      case 'step_regeneration_error':
        console.log('❌ STEP_REGENERATION_ERROR received:', message.data)
        const sessionStore14 = useSessionStore()
        sessionStore14.addMessage('system', message.data.message)
        break
        
      case 'heartbeat':
        // Respond to heartbeat
        sendMessage({
          type: 'heartbeat_ack',
          data: { timestamp: new Date().toISOString() }
        })
        break
        
      case 'heartbeat_ack':
        // Heartbeat acknowledged
        break
        
      default:
        console.warn('Unknown message type:', message.type)
    }
  }

  function handleStreamingChunk(data) {
    const sessionStore = useSessionStore()
    
    if (data.chunk || data.accumulated) {
      const history = sessionStore.conversationHistory
      let lastMessage = history[history.length - 1]
      
      // Find or create the streaming message
      if (!lastMessage || lastMessage.role !== 'assistant' || !lastMessage.streaming) {
        // Create new streaming message
        sessionStore.addMessage('assistant', '', { 
          streaming: true, 
          id: `streaming-${Date.now()}`,
          isStreamingMessage: true 
        })
        lastMessage = history[history.length - 1]
      }
      
      // Update the content based on what we received
      if (data.chunk) {
        // Append chunk to existing content for real-time streaming
        lastMessage.content += data.chunk
      }
      
      // Keep streaming flag until we get the final message
      lastMessage.streaming = true
    }
  }

  function handleCommandOutput(data) {
    // Add command output to execution results
    const sessionStore = useSessionStore()
    
    // Find or create execution result for this step
    const existingResult = sessionStore.executionResults.find(
      r => r.step_index === data.step_index
    )
    
    if (existingResult) {
      if (data.stream === 'stdout') {
        existingResult.stdout += data.line + '\n'
      } else if (data.stream === 'stderr') {
        existingResult.stderr += data.line + '\n'
      }
    }
  }

  function processStateUpdates(updates) {
    const sessionStore = useSessionStore()
    
    if (updates.requirements) {
      Object.assign(sessionStore.requirements, updates.requirements)
    }
    
    if (updates.current_state) {
      sessionStore.updateState(updates.current_state)
    }
    
    if (updates.completion_percentage !== undefined) {
      sessionStore.updateProgress(updates.completion_percentage)
    }
  }

  // Reconnection
  function scheduleReconnect() {
    if (reconnectAttempts.value >= maxReconnectAttempts.value) {
      console.log('Max reconnect attempts reached')
      connectionStatus.value = 'error'
      return
    }
    
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.value), 30000)
    
    console.log(`Scheduling reconnect in ${delay}ms (attempt ${reconnectAttempts.value + 1})`)
    
    reconnectInterval.value = setTimeout(() => {
      reconnectAttempts.value++
      const sessionStore = useSessionStore()
      if (sessionStore.sessionId) {
        connect(sessionStore.sessionId)
      }
    }, delay)
  }

  // Heartbeat
  function startHeartbeat() {
    heartbeatInterval.value = setInterval(() => {
      if (isConnected.value) {
        sendHeartbeat()
      }
    }, 30000) // Send heartbeat every 30 seconds
  }

  function exitSession() {
    disconnect()
    
    const sessionStore = useSessionStore()
    sessionStore.resetSession()
    
    window.location.href = '/'
  }

  return {
    // State
    socket,
    connectionStatus,
    lastMessage,
    messageQueue,
    reconnectAttempts,
    maxReconnectAttempts,
    isProcessingAIMessage,

    // Computed
    isConnected,
    isConnecting,
    shouldReconnect,

    // Actions
    connect,
    disconnect,
    sendMessage,
    sendUserMessage,
    requestSessionState,
    sendHeartbeat,
    exitSession
  }
})