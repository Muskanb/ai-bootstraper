<template>
  <div class="card">
    <div class="card-header">
      <h3 class="text-lg font-semibold text-gray-900">Progress</h3>
      <p class="text-sm text-gray-600">Project creation progress</p>
    </div>

    <!-- Overall Progress -->
    <div class="mb-6">
      <div class="flex justify-between items-center mb-2">
        <span class="text-sm font-medium text-gray-700">Overall Progress</span>
        <span class="text-sm text-gray-600">{{ Math.round(completionPercentage) }}%</span>
      </div>
      <div class="progress-bar">
        <div 
          class="progress-fill"
          :style="{ width: `${completionPercentage}%` }"
        ></div>
      </div>
    </div>

    <!-- State Machine Progress -->
    <div class="space-y-3">
      <div
        v-for="(state, index) in stateFlow"
        :key="state.key"
        class="flex items-center space-x-3 p-2 rounded-lg transition-colors"
        :class="getStateClasses(state, index)"
      >
        <!-- State Icon -->
        <div 
          class="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
          :class="getStateIconClasses(state)"
        >
          <component :is="getStateIcon(state)" class="w-4 h-4" />
        </div>

        <!-- State Info -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center justify-between">
            <p class="text-sm font-medium text-gray-900 truncate">
              {{ state.title }}
            </p>
            <div v-if="state.status === 'completed'" class="text-green-600">
              <CheckIcon class="w-4 h-4" />
            </div>
            <div v-else-if="state.status === 'current'" class="loading-spinner"></div>
          </div>
          <p class="text-xs text-gray-500 truncate">
            {{ state.description }}
          </p>
        </div>
      </div>
    </div>

    <!-- Requirements Summary -->
    <div v-if="hasRequirements" class="mt-6 pt-4 border-t">
      <h4 class="text-sm font-medium text-gray-900 mb-3">Collected Requirements</h4>
      <div class="space-y-2">
        <div v-if="requirements.project_type" class="flex justify-between text-sm">
          <span class="text-gray-600">Project Type:</span>
          <span class="font-medium">{{ formatValue(requirements.project_type) }}</span>
        </div>
        <div v-if="requirements.language" class="flex justify-between text-sm">
          <span class="text-gray-600">Language:</span>
          <span class="font-medium">{{ requirements.language }}</span>
        </div>
        <div v-if="requirements.framework" class="flex justify-between text-sm">
          <span class="text-gray-600">Framework:</span>
          <span class="font-medium">{{ requirements.framework }}</span>
        </div>
        <div v-if="requirements.project_name" class="flex justify-between text-sm">
          <span class="text-gray-600">Project Name:</span>
          <span class="font-medium">{{ requirements.project_name }}</span>
        </div>
        <div v-if="requirements.database" class="flex justify-between text-sm">
          <span class="text-gray-600">Database:</span>
          <span class="font-medium">{{ requirements.database }}</span>
        </div>
      </div>
    </div>

    <!-- Execution Progress -->
    <div v-if="hasExecutionPlan" class="mt-6 pt-4 border-t">
      <h4 class="text-sm font-medium text-gray-900 mb-3">Execution Steps</h4>
      <div class="space-y-2">
        <div
          v-for="(step, index) in executionSteps"
          :key="index"
          class="flex items-center space-x-2 text-sm"
        >
          <div 
            class="w-4 h-4 rounded-full flex-shrink-0"
            :class="getStepStatusClass(step)"
          ></div>
          <span class="truncate">{{ step.description }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import {
  CheckIcon,
  ClockIcon,
  CodeBracketIcon,
  CogIcon,
  CommandLineIcon,
  DocumentCheckIcon,
  PlayIcon,
  UserIcon
} from '@heroicons/vue/24/outline'

const sessionStore = useSessionStore()

// Computed properties
const completionPercentage = computed(() => sessionStore.completionPercentage)
const currentState = computed(() => sessionStore.currentState)
const requirements = computed(() => sessionStore.requirements)
const executionPlan = computed(() => sessionStore.executionPlan)
const executionResults = computed(() => sessionStore.executionResults)

const hasRequirements = computed(() => {
  return Object.values(requirements.value).some(value => 
    value !== null && value !== false && value !== ''
  )
})

const hasExecutionPlan = computed(() => {
  return executionPlan.value && executionPlan.value.steps && executionPlan.value.steps.length > 0
})

const executionSteps = computed(() => {
  if (!hasExecutionPlan.value) return []
  
  return executionPlan.value.steps.map((step, index) => {
    const result = executionResults.value.find(r => r.step_index === index)
    return {
      ...step,
      status: result ? (result.success ? 'completed' : 'failed') : 'pending'
    }
  })
})

// State flow definition
const stateFlow = computed(() => {
  const states = [
    {
      key: 'INIT',
      title: 'Getting Started',
      description: 'Initializing conversation',
      icon: 'UserIcon'
    },
    {
      key: 'ASK_PROJECT_TYPE',
      title: 'Project Type',
      description: 'Determining project type',
      icon: 'CodeBracketIcon'
    },
    {
      key: 'ASK_LANGUAGE_PREFERENCE',
      title: 'Language & Framework',
      description: 'Selecting technology stack',
      icon: 'CogIcon'
    },
    {
      key: 'ASK_PROJECT_NAME_FOLDER',
      title: 'Project Details',
      description: 'Setting name and location',
      icon: 'DocumentCheckIcon'
    },
    {
      key: 'ASK_ADDITIONAL_DETAILS',
      title: 'Additional Features',
      description: 'Database, auth, testing, etc.',
      icon: 'CogIcon'
    },
    {
      key: 'CHECK_SYSTEM_CAPABILITIES',
      title: 'System Check',
      description: 'Checking system capabilities',
      icon: 'CommandLineIcon'
    },
    {
      key: 'VALIDATE_INFO',
      title: 'Validation',
      description: 'Validating requirements',
      icon: 'DocumentCheckIcon'
    },
    {
      key: 'SUMMARY_CONFIRMATION',
      title: 'Confirmation',
      description: 'Final confirmation',
      icon: 'CheckIcon'
    },
    {
      key: 'PLANNING',
      title: 'Planning',
      description: 'Generating execution plan',
      icon: 'ClockIcon'
    },
    {
      key: 'EXECUTING',
      title: 'Executing',
      description: 'Creating project files',
      icon: 'PlayIcon'
    },
    {
      key: 'VERIFYING',
      title: 'Verifying',
      description: 'Running verification tests',
      icon: 'DocumentCheckIcon'
    },
    {
      key: 'COMPLETED',
      title: 'Completed',
      description: 'Project ready to use',
      icon: 'CheckIcon'
    }
  ]
  
  const currentIndex = states.findIndex(s => s.key === currentState.value)
  
  return states.map((state, index) => ({
    ...state,
    status: index < currentIndex ? 'completed' : 
            index === currentIndex ? 'current' : 'pending'
  }))
})

// Methods
function getStateClasses(state, index) {
  if (state.status === 'completed') {
    return 'bg-green-50 border border-green-200'
  } else if (state.status === 'current') {
    return 'bg-blue-50 border border-blue-200'
  } else {
    return 'hover:bg-gray-50'
  }
}

function getStateIconClasses(state) {
  if (state.status === 'completed') {
    return 'bg-green-100 text-green-600'
  } else if (state.status === 'current') {
    return 'bg-blue-100 text-blue-600'
  } else {
    return 'bg-gray-100 text-gray-400'
  }
}

function getStateIcon(state) {
  const icons = {
    UserIcon,
    CheckIcon,
    ClockIcon,
    CodeBracketIcon,
    CogIcon,
    CommandLineIcon,
    DocumentCheckIcon,
    PlayIcon
  }
  
  return icons[state.icon] || ClockIcon
}

function getStepStatusClass(step) {
  if (step.status === 'completed') {
    return 'bg-green-500'
  } else if (step.status === 'failed') {
    return 'bg-red-500'
  } else if (step.status === 'running') {
    return 'bg-blue-500 animate-pulse'
  } else {
    return 'bg-gray-300'
  }
}

function formatValue(value) {
  if (typeof value === 'string') {
    return value.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
  }
  return value
}
</script>