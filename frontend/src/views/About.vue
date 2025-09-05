<template>
  <div class="max-w-4xl mx-auto px-4 py-8">
    <div class="text-center mb-8">
      <h1 class="text-3xl font-bold text-gray-900 mb-4">
        🤖 AI Agent Bootstrapper
      </h1>
      <p class="text-lg text-gray-600">
        Intelligent project scaffolding with AI assistance
      </p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
      <div class="card">
        <h2 class="text-xl font-semibold mb-4">Features</h2>
        <ul class="space-y-2 text-sm text-gray-700">
          <li>• Conversational project setup</li>
          <li>• AI-powered technology recommendations</li>
          <li>• System capability detection</li>
          <li>• Real-time project generation</li>
          <li>• Streaming command execution</li>
          <li>• Smart error handling with fallbacks</li>
          <li>• Multi-language support</li>
          <li>• Docker integration</li>
        </ul>
      </div>

      <div class="card">
        <h2 class="text-xl font-semibold mb-4">Supported Technologies</h2>
        <div class="space-y-3">
          <div>
            <h3 class="font-medium text-sm">Languages</h3>
            <p class="text-sm text-gray-600">Python, JavaScript, TypeScript, Go, Rust</p>
          </div>
          <div>
            <h3 class="font-medium text-sm">Frameworks</h3>
            <p class="text-sm text-gray-600">FastAPI, Express, React, Vue.js, Django, Flask</p>
          </div>
          <div>
            <h3 class="font-medium text-sm">Databases</h3>
            <p class="text-sm text-gray-600">PostgreSQL, MySQL, SQLite, MongoDB</p>
          </div>
          <div>
            <h3 class="font-medium text-sm">Tools</h3>
            <p class="text-sm text-gray-600">Docker, Git, npm, pip, Poetry</p>
          </div>
        </div>
      </div>
    </div>

    <div class="mt-8 text-center">
      <router-link to="/" class="btn-primary">
        Start Creating a Project
      </router-link>
    </div>
  </div>
</template>

<script setup>
// About page - static content
</script>