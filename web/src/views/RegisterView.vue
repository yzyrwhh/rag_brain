<template>
  <div class="auth-wrap">
    <el-card class="auth-card">
      <h2>掌柜智库 · 注册</h2>
      <el-form :model="form" label-width="0" @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名（3-32 位字母数字下划线）" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码（至少 8 位）" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" style="width: 100%" @click="onSubmit">
            注册并登录
          </el-button>
        </el-form-item>
      </el-form>
      <div class="auth-link">
        已有账号？<router-link to="/login">登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function onSubmit() {
  loading.value = true
  try {
    await auth.register(form.username, form.password)
    ElMessage.success('注册成功')
    router.push('/workspace')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-wrap { display: flex; justify-content: center; align-items: center; height: 100vh; background: #f5f7fa; }
.auth-card { width: 360px; padding: 12px 8px; }
.auth-link { text-align: center; color: #909399; font-size: 13px; }
</style>
