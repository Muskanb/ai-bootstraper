<template>
  <span>
    {{ displayedText }}
    <span v-if="isTyping && showCursor" class="cursor">|</span>
  </span>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'

const props = defineProps({
  text: {
    type: String,
    required: true
  },
  isStreaming: {
    type: Boolean,
    default: false
  },
  typingSpeed: {
    type: Number,
    default: 30
  }
})

const displayedText = ref('')
const isTyping = ref(false)
const showCursor = ref(false)
let typingInterval = null
let cursorInterval = null

const isActive = computed(() => props.isStreaming || isTyping.value)

function startTypewriter() {
  if (!props.text) {
    displayedText.value = ''
    return
  }
  
  // Always use typewriter effect for AI messages to make them more engaging
  // Check if text is getting longer (new content)
  const currentLength = displayedText.value.length
  const newLength = props.text.length
  
  if (newLength > currentLength) {
    // If we're streaming, show fast typewriter effect
    if (props.isStreaming) {
      let index = currentLength
      const revealNextChars = () => {
        if (index < newLength) {
          const charsToReveal = Math.min(2, newLength - index)
          displayedText.value = props.text.substring(0, index + charsToReveal)
          index += charsToReveal
          
          if (index < newLength) {
            setTimeout(revealNextChars, 15) // Fast reveal during streaming
          }
        }
      }
      revealNextChars()
      return
    }
    
    // If not streaming but text got longer, use typewriter effect
    isTyping.value = true
    
    // Clear any existing interval
    if (typingInterval) {
      clearInterval(typingInterval)
    }
    
    let index = currentLength
    typingInterval = setInterval(() => {
      if (index < newLength) {
        displayedText.value = props.text.substring(0, index + 1)
        index++
      } else {
        clearInterval(typingInterval)
        typingInterval = null
        isTyping.value = false
      }
    }, 25) // Typewriter speed for new messages
    return
  }
  
  // If text changed and we're not streaming, start typing effect for completed messages
  if (displayedText.value !== props.text && props.text.length > displayedText.value.length) {
    isTyping.value = true
    
    // Clear any existing interval
    if (typingInterval) {
      clearInterval(typingInterval)
    }
    
    const targetText = props.text
    let currentIndex = displayedText.value.length
    
    typingInterval = setInterval(() => {
      if (currentIndex < targetText.length) {
        displayedText.value = targetText.substring(0, currentIndex + 1)
        currentIndex++
      } else {
        clearInterval(typingInterval)
        typingInterval = null
        isTyping.value = false
      }
    }, props.typingSpeed)
  } else {
    // Text got shorter or same, update immediately
    displayedText.value = props.text
  }
}

function startCursor() {
  cursorInterval = setInterval(() => {
    showCursor.value = !showCursor.value
  }, 500)
}

function stopCursor() {
  if (cursorInterval) {
    clearInterval(cursorInterval)
    cursorInterval = null
  }
  showCursor.value = false
}

watch(() => props.text, startTypewriter, { immediate: true })

watch(isActive, (active) => {
  if (active) {
    startCursor()
  } else {
    stopCursor()
  }
})

onMounted(() => {
  startTypewriter()
  if (isActive.value) {
    startCursor()
  }
})

onUnmounted(() => {
  if (typingInterval) {
    clearInterval(typingInterval)
  }
  stopCursor()
})
</script>

<style scoped>
.cursor {
  animation: blink 1s infinite;
  color: #374151;
  font-weight: normal;
}

@keyframes blink {
  0%, 50% {
    opacity: 1;
  }
  51%, 100% {
    opacity: 0;
  }
}
</style>