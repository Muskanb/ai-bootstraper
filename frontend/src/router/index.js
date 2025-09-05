import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home,
    meta: {
      title: 'AI Agent Bootstrapper'
    }
  },
  {
    path: '/session/:sessionId',
    name: 'Session',
    component: () => import('../views/Session.vue'),
    meta: {
      title: 'Session'
    }
  },
  {
    path: '/about',
    name: 'About',
    component: () => import('../views/About.vue'),
    meta: {
      title: 'About'
    }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Navigation guards
router.beforeEach((to, from, next) => {
  // Set page title
  document.title = to.meta.title || 'AI Agent Bootstrapper'
  next()
})

export default router