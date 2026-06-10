import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
// 统一导入el-icon图标
import * as ElIconModules from '@element-plus/icons-vue'
import ElementPlus from 'element-plus';
import { createPinia } from 'pinia'

const app = createApp(App)

// 统一注册el-icon图标
for(let iconName in ElIconModules){
    app.component(iconName,ElIconModules[iconName])
}

app.use(createPinia())
app.use(ElementPlus)
app.mount('#app')
