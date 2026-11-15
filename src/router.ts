import { createRouter, createWebHistory } from 'vue-router'
import Home from './views/Home.vue'
import Results from './views/Results.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home },
    { path: '/search', name: 'search', component: Results },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
