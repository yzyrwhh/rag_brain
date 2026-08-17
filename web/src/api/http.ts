import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1', timeout: 60000 })

// 本模块不 import 任何 store/视图（避免循环依赖）：token 直接读写 localStorage，
// 401 刷新用原生 fetch（不经过本 axios 实例）。

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('sk_access_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

let refreshing: Promise<boolean> | null = null

async function doRefresh(): Promise<boolean> {
  const rt = localStorage.getItem('sk_refresh_token')
  if (!rt) return false
  try {
    const res = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    if (!res.ok) return false
    const data = await res.json()
    localStorage.setItem('sk_access_token', data.access_token)
    localStorage.setItem('sk_refresh_token', data.refresh_token)
    localStorage.setItem('sk_user', JSON.stringify(data.user))
    return true
  } catch {
    return false
  }
}

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const { config, response } = err
    const code = response?.data?.code
    if (response?.status === 401 && code === 'AUTH_INVALID' && !config._retried) {
      config._retried = true
      refreshing = refreshing || doRefresh()
      const ok = await refreshing
      refreshing = null
      if (ok) return api(config)
      localStorage.removeItem('sk_access_token')
      localStorage.removeItem('sk_refresh_token')
      localStorage.removeItem('sk_user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

/** 获取当前 token（fetch 流式请求用，绕开 axios 拦截器） */
export function getToken(): string {
  return localStorage.getItem('sk_access_token') || ''
}
