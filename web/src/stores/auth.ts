import { defineStore } from 'pinia'
import { api } from '../api/http'
import * as authApi from '../api/auth'

const ACCESS_KEY = 'sk_access_token'
const REFRESH_KEY = 'sk_refresh_token'
const USER_KEY = 'sk_user'

interface User {
  user_id: string
  username: string
  role: string
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem(ACCESS_KEY) || '',
    refreshToken: localStorage.getItem(REFRESH_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null') as User | null,
  }),
  getters: {
    isAuthenticated: (s) => !!s.accessToken,
  },
  actions: {
    _persist(tokens: { access_token: string; refresh_token: string; user: User }) {
      this.accessToken = tokens.access_token
      this.refreshToken = tokens.refresh_token
      this.user = tokens.user
      localStorage.setItem(ACCESS_KEY, tokens.access_token)
      localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
      localStorage.setItem(USER_KEY, JSON.stringify(tokens.user))
    },
    async login(username: string, password: string) {
      const r = await authApi.login(username, password)
      this._persist(r)
    },
    async register(username: string, password: string, email?: string) {
      const r = await authApi.register(username, password, email)
      this._persist(r)
    },
    async refresh() {
      if (!this.refreshToken) return false
      try {
        const r = await authApi.refresh(this.refreshToken)
        this._persist(r)
        return true
      } catch {
        this.logout()
        return false
      }
    },
    logout() {
      authApi.logout().catch(() => {})
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})

export { api }
