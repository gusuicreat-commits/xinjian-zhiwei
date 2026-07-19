import 'element-plus/dist/index.css'
import './styles/main.css'

import { ElAlert, ElButton, ElCard, ElSkeleton } from 'element-plus'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElAlert)
app.use(ElButton)
app.use(ElCard)
app.use(ElSkeleton)
app.mount('#app')
