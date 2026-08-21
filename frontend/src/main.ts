import 'element-plus/dist/index.css'
import './styles/main.css'
import './styles/meridian.css'
import './styles/studio-system.css'

import {
  ElAlert,
  ElButton,
  ElCard,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElResult,
  ElSkeleton,
  ElTag,
} from 'element-plus'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
for (const component of [
  ElAlert,
  ElButton,
  ElCard,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElResult,
  ElSkeleton,
  ElTag,
]) {
  app.use(component)
}
app.mount('#app')
