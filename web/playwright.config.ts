import { defineConfig } from '@playwright/test'
export default defineConfig({testDir:'./tests',timeout:120000,workers:1,use:{baseURL:process.env.CLAIR_TEST_URL||'http://127.0.0.1:8765',browserName:'chromium',channel:'msedge',headless:true,viewport:{width:1440,height:1050}},reporter:'list'})
