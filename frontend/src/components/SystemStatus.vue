<template>
  <div class="card">
    <div class="card-header">
      <h3 class="text-lg font-semibold text-gray-900">System Status</h3>
      <p class="text-sm text-gray-600">Detected capabilities</p>
    </div>

    <!-- Loading State -->
    <div v-if="!capabilities && isLoading" class="text-center py-4">
      <div class="loading-spinner mx-auto mb-2"></div>
      <p class="text-sm text-gray-500">Detecting system capabilities...</p>
    </div>

    <!-- No Capabilities -->
    <div v-else-if="!capabilities" class="text-center py-4">
      <div class="text-gray-400 mb-2">
        <svg class="w-8 h-8 mx-auto" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path>
        </svg>
      </div>
      <p class="text-sm text-gray-500">System capabilities not detected yet</p>
    </div>

    <!-- Capabilities Display -->
    <div v-else class="space-y-4">
      <!-- Basic System Info -->
      <div>
        <h4 class="text-sm font-medium text-gray-900 mb-2">System</h4>
        <div class="space-y-1">
          <div class="flex items-center justify-between text-sm">
            <span class="text-gray-600">OS:</span>
            <span class="font-medium">{{ capabilities.os }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-gray-600">Shell:</span>
            <span class="font-medium">{{ capabilities.shell }}</span>
          </div>
        </div>
      </div>

      <!-- Language Runtimes -->
      <div>
        <h4 class="text-sm font-medium text-gray-900 mb-2">Language Runtimes</h4>
        <div class="space-y-2">
          <!-- Python -->
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <div 
                class="status-dot"
                :class="capabilities.python_version ? 'status-success' : 'status-error'"
              ></div>
              <span class="text-sm text-gray-600">Python</span>
            </div>
            <span class="text-sm font-medium">
              {{ capabilities.python_version || 'Not installed' }}
            </span>
          </div>

          <!-- Node.js -->
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <div 
                class="status-dot"
                :class="capabilities.node_version ? 'status-success' : 'status-error'"
              ></div>
              <span class="text-sm text-gray-600">Node.js</span>
            </div>
            <span class="text-sm font-medium">
              {{ capabilities.node_version || 'Not installed' }}
            </span>
          </div>

          <!-- Additional Runtimes -->
          <div 
            v-for="(version, runtime) in additionalRuntimes"
            :key="runtime"
            class="flex items-center justify-between"
          >
            <div class="flex items-center space-x-2">
              <div class="status-dot status-success"></div>
              <span class="text-sm text-gray-600">{{ formatRuntimeName(runtime) }}</span>
            </div>
            <span class="text-sm font-medium">{{ version }}</span>
          </div>
        </div>
      </div>

      <!-- Tools -->
      <div>
        <h4 class="text-sm font-medium text-gray-900 mb-2">Development Tools</h4>
        <div class="grid grid-cols-2 gap-2">
          <!-- Docker -->
          <div class="flex items-center space-x-2">
            <div 
              class="status-dot"
              :class="capabilities.docker_installed ? 'status-success' : 'status-error'"
            ></div>
            <span class="text-xs text-gray-600">Docker</span>
          </div>

          <!-- Git -->
          <div class="flex items-center space-x-2">
            <div 
              class="status-dot"
              :class="capabilities.git_installed ? 'status-success' : 'status-error'"
            ></div>
            <span class="text-xs text-gray-600">Git</span>
          </div>

          <!-- NPM -->
          <div class="flex items-center space-x-2">
            <div 
              class="status-dot"
              :class="capabilities.npm_version ? 'status-success' : 'status-error'"
            ></div>
            <span class="text-xs text-gray-600">npm</span>
          </div>

          <!-- Package Managers -->
          <div 
            v-for="manager in visiblePackageManagers"
            :key="manager"
            class="flex items-center space-x-2"
          >
            <div class="status-dot status-success"></div>
            <span class="text-xs text-gray-600">{{ manager }}</span>
          </div>
        </div>
      </div>

      <!-- Package Managers (if many) -->
      <div v-if="capabilities.available_package_managers && capabilities.available_package_managers.length > 4">
        <h4 class="text-sm font-medium text-gray-900 mb-2">Package Managers</h4>
        <div class="flex flex-wrap gap-1">
          <span 
            v-for="manager in capabilities.available_package_managers"
            :key="manager"
            class="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-gray-100 text-gray-800"
          >
            {{ manager }}
          </span>
        </div>
      </div>

      <!-- Recommendations -->
      <div v-if="recommendations.length > 0" class="pt-4 border-t">
        <h4 class="text-sm font-medium text-gray-900 mb-2">Recommendations</h4>
        <div class="space-y-2">
          <div 
            v-for="rec in recommendations"
            :key="rec.title"
            class="p-2 rounded-md text-xs"
            :class="getRecommendationClass(rec.type)"
          >
            <div class="font-medium">{{ rec.title }}</div>
            <div class="text-xs opacity-75">{{ rec.description }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Refresh Button -->
    <div class="mt-4 pt-4 border-t">
      <button 
        @click="refreshCapabilities"
        :disabled="isRefreshing"
        class="w-full btn-secondary text-xs"
      >
        <span v-if="isRefreshing" class="flex items-center justify-center">
          <div class="loading-spinner mr-2"></div>
          Refreshing...
        </span>
        <span v-else>Refresh System Status</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useSessionStore } from '../stores/session'
import { useWebSocketStore } from '../stores/websocket'

const sessionStore = useSessionStore()
const wsStore = useWebSocketStore()

// Local state
const isRefreshing = ref(false)

// Computed properties
const capabilities = computed(() => sessionStore.systemCapabilities)
const isLoading = computed(() => sessionStore.isLoading && !capabilities.value)

const additionalRuntimes = computed(() => {
  if (!capabilities.value || !capabilities.value.available_runtimes) return {}
  
  const runtimes = { ...capabilities.value.available_runtimes }
  
  // Remove already displayed runtimes
  delete runtimes.python
  delete runtimes.python3
  delete runtimes.node
  
  return runtimes
})

const visiblePackageManagers = computed(() => {
  if (!capabilities.value || !capabilities.value.available_package_managers) return []
  
  // Show first 4 package managers (excluding npm which is shown separately)
  return capabilities.value.available_package_managers
    .filter(pm => pm !== 'npm')
    .slice(0, 3)
})

const recommendations = computed(() => {
  if (!capabilities.value) return []
  
  const recs = []
  
  // Check for missing essential tools
  if (!capabilities.value.python_version && !capabilities.value.node_version) {
    recs.push({
      type: 'warning',
      title: 'No Runtime Detected',
      description: 'Install Python or Node.js to create projects'
    })
  }
  
  if (!capabilities.value.git_installed) {
    recs.push({
      type: 'info',
      title: 'Git Not Found',
      description: 'Install Git for version control features'
    })
  }
  
  if (!capabilities.value.docker_installed) {
    recs.push({
      type: 'info',
      title: 'Docker Not Found',
      description: 'Install Docker for containerization features'
    })
  }
  
  // Positive recommendations
  if (capabilities.value.python_version && capabilities.value.available_package_managers.includes('pip')) {
    recs.push({
      type: 'success',
      title: 'Python Ready',
      description: 'Can create Python projects with pip'
    })
  }
  
  if (capabilities.value.node_version && capabilities.value.npm_version) {
    recs.push({
      type: 'success',
      title: 'Node.js Ready',
      description: 'Can create JavaScript/TypeScript projects'
    })
  }
  
  return recs
})

// Methods
function formatRuntimeName(runtime) {
  const names = {
    'go': 'Go',
    'rust': 'Rust',
    'java': 'Java',
    'php': 'PHP',
    'ruby': 'Ruby',
    'dotnet': '.NET',
    'swift': 'Swift'
  }
  
  return names[runtime] || runtime.charAt(0).toUpperCase() + runtime.slice(1)
}

function getRecommendationClass(type) {
  const classes = {
    success: 'bg-green-50 text-green-800',
    warning: 'bg-yellow-50 text-yellow-800',
    info: 'bg-blue-50 text-blue-800',
    error: 'bg-red-50 text-red-800'
  }
  
  return classes[type] || classes.info
}

async function refreshCapabilities() {
  isRefreshing.value = true
  
  try {
    // Send message to backend to refresh capabilities
    wsStore.sendMessage({
      type: 'refresh_capabilities'
    })
    
    // Simulate refresh delay
    await new Promise(resolve => setTimeout(resolve, 2000))
    
  } catch (error) {
    console.error('Failed to refresh capabilities:', error)
  } finally {
    isRefreshing.value = false
  }
}
</script>