import { api } from './http'

export interface TokenPair {
  access_token: string
  refresh_token: string
  user: { user_id: string; username: string; role: string }
}

export async function login(username: string, password: string): Promise<TokenPair> {
  const r = await api.post<TokenPair>('/auth/login', { username, password })
  return r.data
}

export async function register(username: string, password: string, email?: string): Promise<TokenPair> {
  const r = await api.post<TokenPair>('/auth/register', { username, password, email })
  return r.data
}

export async function refresh(refreshToken: string): Promise<TokenPair> {
  const r = await api.post<TokenPair>('/auth/refresh', { refresh_token: refreshToken })
  return r.data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}
