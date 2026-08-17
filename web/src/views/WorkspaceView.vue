<template>
  <div class="chat-layout">
    <!-- 会话列表 -->
    <aside class="sessions">
      <button class="new-session" @click="newSession">＋ 新对话</button>
      <div
        v-for="s in sessions"
        :key="s.session_id"
        class="session-item"
        :class="{ active: s.session_id === currentSessionId }"
        @click="switchSession(s.session_id)"
      >
        <div class="s-title">{{ s.title }}</div>
        <div class="s-time">{{ fmtTime(s.updated_at) }}</div>
      </div>
      <div v-if="!sessions.length" class="empty-tip">还没有会话</div>
    </aside>

    <!-- 聊天区 -->
    <div class="chat-area">
      <div ref="scrollRef" class="messages">
        <template v-if="!messages.length">
          <div class="welcome">
            <h2>你好，{{ auth.user?.username }}</h2>
            <p>问知识库、查资料、闲聊……</p>
          </div>
        </template>

        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="avatar">{{ m.role === 'user' ? '我' : '智' }}</div>
          <div class="bubble">
            <span v-if="m.role === 'assistant' && m.intent" class="intent-tag" :class="m.intent">
              {{ intentLabel(m.intent) }}
            </span>
            <span class="text" :class="{ 'stream-cursor': streaming && i === messages.length - 1 && m.role === 'assistant' }">
              {{ m.text }}
            </span>
            <div v-if="m.role === 'assistant' && m.sources?.length" class="sources">
              <div v-for="s in m.sources" :key="s.doc_id" class="source-card" @click="gotoDoc(s.doc_id)">
                📄 {{ s.title || s.doc_id }}
              </div>
            </div>
            <div v-if="m.role === 'assistant' && m.text" class="bubble-actions">
              <button class="remember-btn" @click="remember(m.text)">＋ 记住这条经验</button>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <div class="input-box">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入问题，Enter 发送，Shift+Enter 换行（当前空间：{{ space.activeSpace?.name || '全部' }}）"
            @keydown="onKeydown"
          />
          <button class="send-btn" :disabled="sending || !input.trim()" @click="send">
            <el-icon v-if="sending" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><Promotion /></el-icon>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Loading, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { useSpaceStore } from '../stores/space'
import { listSessions, getSessionMessages, streamChat, type SessionItem } from '../api/chat'
import { createMemory } from '../api/memory'

interface Msg {
  role: 'user' | 'assistant'
  text: string
  intent?: string
  sources?: { doc_id: string; title: string }[]
}

const auth = useAuthStore()
const space = useSpaceStore()
const router = useRouter()
const sessions = ref<SessionItem[]>([])
const currentSessionId = ref('')
const messages = reactive<Msg[]>([])
const input = ref('')
const sending = ref(false)
const streaming = ref(false)
const scrollRef = ref<HTMLElement>()

onMounted(async () => {
  await space.load()
  await loadSessions()
})

async function loadSessions() {
  try {
    sessions.value = await listSessions()
  } catch {
    /* 忽略 */
  }
}

async function newSession() {
  currentSessionId.value = ''
  messages.splice(0)
  input.value = ''
}

async function switchSession(sid: string) {
  currentSessionId.value = sid
  messages.splice(0)
  const items = await getSessionMessages(sid)
  for (const m of items) {
    messages.push({
      role: m.role,
      text: m.text,
      intent: m.metadata?.intent,
      sources: m.metadata?.sources,
    })
  }
}

async function scrollBottom() {
  await nextTick()
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight })
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

async function send() {
  const q = input.value.trim()
  if (!q || sending.value) return
  input.value = ''
  messages.push({ role: 'user', text: q })
  messages.push({ role: 'assistant', text: '' })
  sending.value = true
  streaming.value = true
  await scrollBottom()

  const spacesToUse = space.activeSpaceId ? [space.activeSpaceId] : []
  try {
    await streamChat(
      q,
      spacesToUse,
      {
        onDelta: (text) => {
          messages[messages.length - 1].text += text
          scrollBottom()
        },
        onFinal: (p) => {
          const last = messages[messages.length - 1]
          last.text = p.text
          last.intent = p.intent
          last.sources = p.sources
          scrollBottom()
        },
      },
      currentSessionId.value || undefined,
    )
    await loadSessions()
  } catch (e: any) {
    messages[messages.length - 1].text = '请求失败，请稍后再试。'
    ElMessage.error(e?.message || '对话失败')
  } finally {
    sending.value = false
    streaming.value = false
    await scrollBottom()
  }
}

function intentLabel(intent?: string) {
  const map: Record<string, string> = {
    knowledge_query: '知识问答',
    general_chat: '闲聊',
    unclear: '待澄清',
    knowledge_import: '导入提示',
  }
  return map[intent || ''] || intent || ''
}

function fmtTime(ts?: string) {
  if (!ts) return ''
  const d = new Date(ts)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function gotoDoc(_docId: string) {
  router.push('/knowledge')
}

async function remember(text: string) {
  if (!text) return
  try {
    await createMemory(text, 'dev_case')
    ElMessage.success('已记住，可在知识库-记忆 中查看')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '记忆失败')
  }
}
</script>

<style scoped>
.chat-layout { display: flex; height: 100%; }
.sessions {
  width: 200px; border-right: 1px solid var(--sk-border);
  padding: 12px 8px; overflow-y: auto; background: #fbfbfd;
  display: flex; flex-direction: column; gap: 4px;
}
.new-session {
  border: 1px dashed var(--sk-border); background: #fff; border-radius: var(--sk-radius-sm);
  padding: 8px; color: var(--el-color-primary); cursor: pointer; margin-bottom: 8px;
  font-size: 13px;
}
.session-item { padding: 8px 10px; border-radius: var(--sk-radius-sm); cursor: pointer; }
.session-item:hover { background: #f2f3f8; }
.session-item.active { background: var(--el-color-primary-light-9); }
.s-title { font-size: 13px; color: var(--sk-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.s-time { font-size: 11px; color: var(--sk-text-3); margin-top: 2px; }
.empty-tip { color: var(--sk-text-3); font-size: 12px; text-align: center; margin-top: 24px; }

.chat-area { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.messages { flex: 1; overflow-y: auto; padding: 24px 32px; display: flex; flex-direction: column; gap: 16px; }
.welcome { margin: 60px auto; text-align: center; color: var(--sk-text-2); }
.welcome h2 { font-size: 22px; color: var(--sk-text); }
.msg { display: flex; gap: 10px; }
.msg.user { flex-direction: row-reverse; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: #fff;
}
.msg.user .avatar { background: var(--sk-msg-user); }
.msg.assistant .avatar { background: #10b981; }
.bubble {
  max-width: 72%; padding: 10px 14px; border-radius: var(--sk-radius);
  box-shadow: var(--sk-shadow); background: var(--sk-msg-bot);
  white-space: pre-wrap; word-break: break-word; line-height: 1.7;
}
.msg.user .bubble { background: var(--sk-msg-user); color: #fff; }
.intent-tag {
  display: inline-block; font-size: 11px; border-radius: 4px; padding: 1px 6px;
  margin-right: 6px; color: #fff; vertical-align: 1px;
}
.intent-tag.knowledge_query { background: var(--sk-tag-knowledge); }
.intent-tag.general_chat { background: var(--sk-tag-general); }
.intent-tag.unclear { background: var(--sk-tag-unclear); }
.sources { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.source-card {
  font-size: 12px; color: var(--sk-text-2); background: #f7f8fb;
  border-radius: 6px; padding: 4px 8px; cursor: pointer;
}
.source-card:hover { background: #eef1fd; color: var(--el-color-primary); }
.bubble-actions { margin-top: 6px; }
.remember-btn {
  border: 1px dashed var(--sk-border); background: transparent; color: var(--sk-text-3);
  font-size: 12px; border-radius: 6px; padding: 2px 8px; cursor: pointer;
}
.remember-btn:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }

.input-area { padding: 12px 32px 20px; }
.input-box { display: flex; gap: 10px; align-items: flex-end; }
.send-btn {
  width: 40px; height: 40px; border-radius: 10px; border: none;
  background: var(--el-color-primary); color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center; font-size: 18px;
}
.send-btn:disabled { background: #c0c4cc; cursor: not-allowed; }
</style>
