<template>
  <div class="shell">
    <!-- 左侧导航 -->
    <aside class="sidebar">
      <div class="logo" @click="$router.push('/workspace')">
        <span class="logo-dot"></span>
        掌柜智库
      </div>
      <nav class="nav">
        <router-link to="/workspace" class="nav-item" active-class="active">
          <el-icon><ChatDotRound /></el-icon> 对话
        </router-link>
        <router-link to="/knowledge" class="nav-item" active-class="active">
          <el-icon><Collection /></el-icon> 知识库
        </router-link>
      </nav>
      <div class="spacer" />
      <div class="user">
        <el-dropdown @command="onCommand">
          <span class="user-name">{{ auth.user?.username }}</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>

    <!-- 主内容 -->
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ChatDotRound, Collection } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.shell { display: flex; height: 100vh; }
.sidebar {
  width: var(--sk-sidebar-w);
  background: var(--sk-bg-sidebar);
  border-right: 1px solid var(--sk-border);
  display: flex;
  flex-direction: column;
  padding: 16px 12px;
  flex-shrink: 0;
}
.logo { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 16px; padding: 4px 8px 16px; cursor: pointer; }
.logo-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--el-color-primary); }
.nav { display: flex; flex-direction: column; gap: 4px; }
.nav-item {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px; border-radius: var(--sk-radius-sm);
  color: var(--sk-text-2); text-decoration: none; font-size: 14px;
  transition: background .15s, color .15s;
}
.nav-item:hover { background: #f3f4f8; }
.nav-item.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); font-weight: 600; }
.spacer { flex: 1; }
.user { padding: 12px 8px 0; border-top: 1px solid var(--sk-border); }
.user-name { color: var(--sk-text-2); cursor: pointer; font-size: 13px; }
.content { flex: 1; min-width: 0; overflow: hidden; }
</style>
