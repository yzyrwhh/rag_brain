import { defineStore } from 'pinia'
import * as kb from '../api/knowledge'

export interface Space {
  space_id: string
  name: string
  description?: string
  type?: string
}

export const useSpaceStore = defineStore('space', {
  state: () => ({
    spaces: [] as Space[],
    activeSpaceId: localStorage.getItem('sk_space') || '',
  }),
  getters: {
    activeSpace: (s) => s.spaces.find((x) => x.space_id === s.activeSpaceId) || null,
  },
  actions: {
    async load() {
      this.spaces = await kb.listSpaces()
      // 若当前空间已被删除/失效，回退到第一个
      if (!this.spaces.find((s) => s.space_id === this.activeSpaceId)) {
        this.activeSpaceId = this.spaces[0]?.space_id || ''
        localStorage.setItem('sk_space', this.activeSpaceId)
      }
    },
    setActive(id: string) {
      this.activeSpaceId = id
      localStorage.setItem('sk_space', id)
    },
  },
})
