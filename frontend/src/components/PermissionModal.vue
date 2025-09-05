<template>
  <!-- Modal Backdrop -->
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg max-w-md w-full mx-4 shadow-xl">
      <!-- Modal Header -->
      <div class="px-6 py-4 border-b border-gray-200">
        <div class="flex items-center">
          <div class="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center mr-3">
            <svg class="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path>
            </svg>
          </div>
          <div>
            <h3 class="text-lg font-semibold text-gray-900">
              Permission Required
            </h3>
            <p class="text-sm text-gray-600">
              {{ getPermissionTitle() }}
            </p>
          </div>
        </div>
      </div>

      <!-- Modal Body -->
      <div class="px-6 py-4">
        <div class="space-y-4">
          <!-- Permission Description -->
          <div>
            <p class="text-sm text-gray-700 mb-3">
              {{ permission.question || permission.reason }}
            </p>
          </div>

          <!-- Permission Details -->
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="space-y-2">
              <div class="flex justify-between text-sm">
                <span class="text-gray-600">Type:</span>
                <span class="font-medium">{{ formatPermissionType() }}</span>
              </div>
              
              <div class="flex justify-between text-sm">
                <span class="text-gray-600">Scope:</span>
                <span class="font-medium font-mono text-xs">{{ permission.scope }}</span>
              </div>
              
              <div v-if="permission.reason" class="text-sm">
                <span class="text-gray-600">Reason:</span>
                <p class="mt-1 text-gray-700">{{ permission.reason }}</p>
              </div>
            </div>
          </div>

          <!-- What This Allows -->
          <div v-if="getPermissionDetails().length > 0">
            <h4 class="text-sm font-medium text-gray-900 mb-2">This permission allows:</h4>
            <ul class="space-y-1">
              <li 
                v-for="detail in getPermissionDetails()"
                :key="detail"
                class="text-sm text-gray-600 flex items-start"
              >
                <svg class="w-4 h-4 text-blue-500 mt-0.5 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path>
                </svg>
                {{ detail }}
              </li>
            </ul>
          </div>

          <!-- Security Notice -->
          <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
            <div class="flex">
              <svg class="w-5 h-5 text-yellow-600 mt-0.5 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"></path>
              </svg>
              <div>
                <p class="text-sm font-medium text-yellow-800">Security Notice</p>
                <p class="text-sm text-yellow-700 mt-1">
                  Only grant permissions you trust. You can revoke this permission at any time.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="px-6 py-4 border-t border-gray-200 flex justify-end space-x-3">
        <button 
          @click="denyPermission"
          class="btn-secondary"
        >
          Deny
        </button>
        <button 
          @click="approvePermission"
          class="btn-primary"
        >
          Allow
        </button>
      </div>

      <!-- Remember Choice -->
      <div class="px-6 pb-4">
        <label class="flex items-center">
          <input 
            v-model="rememberChoice"
            type="checkbox" 
            class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span class="ml-2 text-sm text-gray-600">
            Remember my choice for similar permissions
          </span>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

// Props
const props = defineProps({
  permission: {
    type: Object,
    required: true
  }
})

// Emits
const emit = defineEmits(['approve', 'deny'])

// Local state
const rememberChoice = ref(false)

// Computed
const permissionType = computed(() => props.permission.permission_type || 'unknown')

// Methods
function getPermissionTitle() {
  const type = permissionType.value
  
  const titles = {
    global: 'Global System Access',
    folder: 'Folder Access',
    command: 'Command Execution',
    file: 'File Access'
  }
  
  return titles[type] || 'Permission Request'
}

function formatPermissionType() {
  const type = permissionType.value
  
  const formatted = {
    global: 'Global Access',
    folder: 'Folder Access', 
    command: 'Command Execution',
    file: 'File Access'
  }
  
  return formatted[type] || type.charAt(0).toUpperCase() + type.slice(1)
}

function getPermissionDetails() {
  const type = permissionType.value
  const scope = props.permission.scope || ''
  
  const details = {
    global: [
      'Read system information (OS, installed tools)',
      'Create files and folders anywhere on the system',
      'Execute commands to install dependencies',
      'Access environment variables'
    ],
    folder: [
      `Create and modify files in: ${scope}`,
      'Execute commands within this folder',
      'Read existing files in this directory'
    ],
    command: [
      `Execute the command: ${scope}`,
      'Stream command output in real-time',
      'Handle command failures with fallbacks'
    ],
    file: [
      `Access the file: ${scope}`,
      'Read file contents',
      'Modify file if needed'
    ]
  }
  
  return details[type] || []
}

function approvePermission() {
  emit('approve', {
    ...props.permission,
    remember: rememberChoice.value
  })
}

function denyPermission() {
  emit('deny', {
    ...props.permission,
    remember: rememberChoice.value
  })
}

// Handle escape key
function handleKeydown(event) {
  if (event.key === 'Escape') {
    denyPermission()
  }
}

// Add event listener for escape key
document.addEventListener('keydown', handleKeydown)

// Cleanup
import { onUnmounted } from 'vue'
onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
/* Modal animation */
.fixed {
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.bg-white {
  animation: slideUp 0.3s ease-out;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}
</style>