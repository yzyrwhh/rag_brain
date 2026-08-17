<template>
  <div class="kb-page">
    <div class="kb-head">
      <h2>知识库</h2>
      <div class="space-bar">
        <el-select v-model="space.activeSpaceId" placeholder="选择空间" style="width: 200px" @change="onSpaceChange">
          <el-option v-for="s in space.spaces" :key="s.space_id" :label="s.name" :value="s.space_id" />
        </el-select>
        <el-popover placement="bottom" width="240">
          <template #reference>
            <el-button size="small" circle><el-icon><Plus /></el-icon></el-button>
          </template>
          <div style="display:flex; gap:8px">
            <el-input v-model="newSpace" placeholder="新空间名" size="small" />
            <el-button size="small" type="primary" @click="createSpace">创建</el-button>
          </div>
        </el-popover>
      </div>
    </div>

    <el-tabs v-model="tab" class="kb-tabs">
      <!-- 文档 -->
      <el-tab-pane label="文档" name="docs">
        <el-table :data="docs" style="width: 100%">
          <el-table-column prop="title" label="标题" min-width="180" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="domain" label="领域" width="80" />
          <el-table-column prop="chunk_count" label="切片数" width="80" />
          <el-table-column label="标签" min-width="140">
            <template #default="{ row }">
              <el-tag v-for="t in (row.tags || []).slice(0, 3)" :key="t" size="small" type="info" style="margin-right: 4px">{{ t }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" text @click="askAbout(row)">问答</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 上传 -->
      <el-tab-pane label="上传" name="upload">
        <el-upload
          drag
          :auto-upload="false"
          :limit="1"
          :on-change="onFileChange"
          :file-list="fileList"
          accept=".pdf,.md,.markdown"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽或点击选择文件（PDF / Markdown）</div>
        </el-upload>
        <div class="upload-bar">
          <el-select v-model="domain" size="small" style="width: 120px">
            <el-option label="通用" value="general" />
            <el-option label="开发" value="dev" />
            <el-option label="论文" value="paper" />
          </el-select>
          <el-button type="primary" :loading="uploading" @click="doUpload">上传导入</el-button>
        </div>
        <div v-if="uploadTaskId" class="task-progress">
          <div class="phase-steps">
            <div v-for="p in phases" :key="p.name" class="phase-step" :class="p.status">
              <span class="dot"></span>{{ p.label }}
            </div>
          </div>
          <div ref="logRef" class="task-log">
            <div v-for="(l, i) in uploadLogs" :key="i" class="log-line">{{ l }}</div>
          </div>
          <div class="task-status">{{ uploadStatusText }}</div>
        </div>
      </el-tab-pane>

      <!-- 检索 -->
      <el-tab-pane label="检索" name="search">
        <div class="search-bar">
          <el-input v-model="searchQ" placeholder="输入查询内容" @keyup.enter="doSearch" />
          <el-button type="primary" :loading="searching" @click="doSearch">检索</el-button>
        </div>
        <div v-if="searchResults.length" class="search-results">
          <div v-for="(h, i) in searchResults" :key="i" class="search-item sk-card">
            <div class="search-score">相关度 {{ h.score }}</div>
            <div class="search-text">{{ h.text }}</div>
          </div>
        </div>
        <el-empty v-else-if="searched" description="无结果" />
      </el-tab-pane>

      <!-- 问答 -->
      <el-tab-pane label="问答" name="ask">
        <div class="search-bar">
          <el-input v-model="askQ" placeholder="针对知识库提问" @keyup.enter="doAsk" />
          <el-button type="primary" :loading="asking" @click="doAsk">提问</el-button>
        </div>
        <div v-if="answer" class="ask-result sk-card">
          <div class="ask-text">{{ answer }}</div>
          <div v-for="s in answerSources" :key="s.doc_id" class="source-card">📄 {{ s.title || s.doc_id }}</div>
        </div>
      </el-tab-pane>

      <!-- 记忆 -->
      <el-tab-pane label="记忆" name="memory">
        <div class="search-bar">
          <el-input v-model="memoryQ" placeholder="搜索记忆内容" @keyup.enter="doMemorySearch" />
          <el-button type="primary" @click="doMemorySearch">搜索</el-button>
          <el-button @click="loadMemories">全部</el-button>
        </div>
        <el-table :data="memories" size="small">
          <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
          <el-table-column prop="type" label="类型" width="90" />
          <el-table-column label="适用场景" min-width="150">
            <template #default="{ row }">
              <el-tag v-for="s in (row.scenarios || []).slice(0, 3)" :key="s" size="small" type="success" style="margin-right: 4px">{{ s }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="重要度" width="70">
            <template #default="{ row }">★{{ row.importance }}</template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="{ row }">
              <el-button size="small" text type="danger" @click="removeMemory(row.memory_id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { Plus, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useSpaceStore } from '../stores/space'
import * as kb from '../api/knowledge'
import { subscribeTaskEvents } from '../api/task'
import { listMemories, searchMemories, deleteMemory, type MemoryItem } from '../api/memory'

const space = useSpaceStore()
const tab = ref('docs')
const docs = ref<kb.Document[]>([])
const newSpace = ref('')

const fileList = ref<any[]>([])
const domain = ref('general')
const uploading = ref(false)
const uploadTaskId = ref('')
const uploadDone = ref<boolean | null>(null)
const uploadStatusText = ref('')
const uploadLogs = ref<string[]>([])
const logRef = ref<HTMLElement>()
const phases = reactive([
  { name: 'parsing', label: '解析', status: 'pending' },
  { name: 'splitting', label: '切分', status: 'pending' },
  { name: 'embedding', label: '向量化', status: 'pending' },
  { name: 'importing', label: '入库', status: 'pending' },
])

const searchQ = ref('')
const searchResults = ref<kb.SearchHit[]>([])
const searching = ref(false)
const searched = ref(false)

const askQ = ref('')
const answer = ref('')
const answerSources = ref<{ doc_id: string; title: string }[]>([])
const asking = ref(false)

const memoryQ = ref('')
const memories = ref<MemoryItem[]>([])

async function loadMemories() {
  memories.value = await listMemories()
}

async function doMemorySearch() {
  memories.value = memoryQ.value.trim()
    ? await searchMemories(memoryQ.value.trim())
    : await listMemories()
}

async function removeMemory(memoryId: string) {
  await deleteMemory(memoryId)
  memories.value = memories.value.filter((m) => m.memory_id !== memoryId)
  ElMessage.success('已删除')
}

onMounted(async () => {
  await space.load()
  if (space.activeSpaceId) loadDocs()
})

watch(() => space.activeSpaceId, () => {
  if (space.activeSpaceId) loadDocs()
  else docs.value = []
})

watch(tab, (t) => {
  if (t === 'memory') loadMemories()
})

function onSpaceChange(id: string) {
  space.setActive(id)
}

async function createSpace() {
  if (!newSpace.value.trim()) return
  await kb.createSpace(newSpace.value.trim())
  newSpace.value = ''
  await space.load()
  ElMessage.success('空间已创建')
}

async function loadDocs() {
  if (!space.activeSpaceId) return
  docs.value = await kb.listDocuments(space.activeSpaceId)
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    pending: '排队中', parsing: '解析中', splitting: '切分中',
    embedding: '向量化', importing: '入库中', completed: '完成', failed: '失败',
  }
  return map[s] || s
}
function statusType(s: string): any {
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'pending') return 'info'
  return 'warning'
}

function onFileChange(f: any) {
  fileList.value = [f]
}

async function doUpload() {
  if (!space.activeSpaceId || !fileList.value[0]) return ElMessage.warning('请选择空间和文件')
  uploading.value = true
  uploadDone.value = null
  uploadStatusText.value = '上传中…'
  uploadLogs.value = []
  for (const p of phases) p.status = 'pending'
  try {
    const r = await kb.uploadDocument(space.activeSpaceId, fileList.value[0].raw, domain.value)
    uploadTaskId.value = r.task_id
    uploadStatusText.value = '排队中…'

    const pushLog = (text: string) => {
      uploadLogs.value.push(text)
      if (uploadLogs.value.length > 200) uploadLogs.value.shift()
      nextTick(() => logRef.value?.scrollTo({ top: logRef.value.scrollHeight }))
    }

    // 订阅任务 SSE：阶段步骤 + 细粒度日志（agent.thinking / tool.result）
    let settled = false
    try {
      await subscribeTaskEvents(r.task_id, (ev) => {
        if (ev.type === 'node.start') {
          const node = ev.payload?.node || ''
          setPhase(node, 'running')
          uploadStatusText.value = statusLabel(node)
        } else if (ev.type === 'node.end') {
          setPhase(ev.payload?.node, 'done')
        } else if (ev.type === 'agent.thinking') {
          pushLog(ev.payload?.text || '')
        } else if (ev.type === 'tool.result' && ev.payload?.summary) {
          pushLog(ev.payload.summary)
        } else if (ev.type === 'task.completed') {
          uploadStatusText.value = '完成'
          uploadDone.value = true
          settled = true
          tab.value = 'docs'
          loadDocs()
        } else if (ev.type === 'task.failed') {
          uploadStatusText.value = `失败：${ev.payload?.error?.message || '未知错误'}`
          pushLog(`任务失败：${ev.payload?.error?.message || ''}`)
          uploadDone.value = false
          settled = true
        }
      })
    } catch {
      // SSE 失败 → 回退轮询一次兜底
    }
    if (!settled) {
      let st = ''
      for (let i = 0; i < 60; i++) {
        await new Promise((res) => setTimeout(res, 3000))
        let doc: kb.Document
        try {
          doc = await kb.getDocument(r.doc_id)
        } catch {
          continue
        }
        st = doc.status
        uploadStatusText.value = statusLabel(st)
        if (st === 'completed' || st === 'failed') {
          uploadDone.value = st === 'completed'
          break
        }
      }
    }
    fileList.value = []
    loadDocs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '上传失败')
    uploadDone.value = false
    uploadStatusText.value = '上传失败'
  } finally {
    uploading.value = false
  }
}

function setPhase(name: string, status: string) {
  const p = phases.find((x) => x.name === name)
  if (p) p.status = status
}

async function doSearch() {
  if (!searchQ.value.trim()) return
  searching.value = true
  searched.value = true
  try {
    const spacesToUse = space.activeSpaceId ? [space.activeSpaceId] : []
    const r = await kb.searchKnowledge(searchQ.value.trim(), spacesToUse, 5)
    searchResults.value = r.results
  } finally {
    searching.value = false
  }
}

async function askAbout(_row: kb.Document) {
  askQ.value = `请总结文档「${_row.title}」的核心内容`
  tab.value = 'ask'
  doAsk()
}

async function doAsk() {
  if (!askQ.value.trim()) return
  asking.value = true
  try {
    const spacesToUse = space.activeSpaceId ? [space.activeSpaceId] : []
    const r = await kb.askKnowledge(askQ.value.trim(), spacesToUse)
    answer.value = r.answer
    answerSources.value = r.sources
  } finally {
    asking.value = false
  }
}
</script>

<style scoped>
.kb-page { padding: 20px 28px; height: 100%; overflow-y: auto; }
.kb-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.kb-head h2 { margin: 0; font-size: 18px; }
.space-bar { display: flex; gap: 8px; align-items: center; }
.kb-tabs { background: var(--sk-bg-card); border-radius: var(--sk-radius); padding: 8px 20px 20px; box-shadow: var(--sk-shadow); border: 1px solid var(--sk-border); }
.upload-bar { display: flex; gap: 10px; margin-top: 12px; align-items: center; }
.task-progress { margin-top: 16px; width: 80%; }
.task-status { font-size: 12px; color: var(--sk-text-3); margin-top: 6px; }
.task-log {
  max-height: 180px; overflow-y: auto; background: #0f1419; color: #c9d1d9;
  border-radius: 8px; padding: 8px 12px; font-family: ui-monospace, Consolas, monospace;
  font-size: 12px; line-height: 1.7; margin-top: 8px;
}
.log-line { white-space: pre-wrap; word-break: break-all; }
.phase-steps { display: flex; gap: 20px; }
.phase-step { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--sk-text-3); }
.phase-step .dot { width: 8px; height: 8px; border-radius: 50%; background: #d5d7de; }
.phase-step.running { color: var(--el-color-primary); font-weight: 600; }
.phase-step.running .dot { background: var(--el-color-primary); animation: blink 1s steps(2) infinite; }
.phase-step.done { color: #10b981; }
.phase-step.done .dot { background: #10b981; }
.search-bar { display: flex; gap: 10px; margin-bottom: 16px; }
.search-results { display: flex; flex-direction: column; gap: 10px; }
.search-item { padding: 12px 16px; }
.search-score { font-size: 12px; color: var(--el-color-primary); margin-bottom: 6px; }
.search-text { color: var(--sk-text); line-height: 1.7; }
.ask-result { padding: 16px 20px; margin-top: 12px; }
.ask-text { white-space: pre-wrap; line-height: 1.8; margin-bottom: 10px; }
.source-card { font-size: 12px; color: var(--sk-text-2); background: #f7f8fb; border-radius: 6px; padding: 4px 8px; margin-top: 4px; }
</style>
