import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import AppShell from '../components/AppShell.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('../views/RegisterView.vue') },
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', redirect: '/workspace' },
        {
          path: 'workspace',
          name: 'workspace',
          component: () => import('../views/WorkspaceView.vue'),
          meta: { requiresAuth: true },
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('../views/KnowledgeView.vue'),
          meta: { requiresAuth: true },
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if ((to.name === 'login' || to.name === 'register') && auth.isAuthenticated) {
    return { name: 'workspace' }
  }
})

export default router
