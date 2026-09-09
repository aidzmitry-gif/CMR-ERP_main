const { defineConfig } = require('../frontend/node_modules/@playwright/test');
module.exports = defineConfig({
  testDir: '../frontend/e2e', timeout: 45000, expect: {timeout:12000},
  fullyParallel:false, retries:0, workers:1, reporter:'list',
  outputDir:'../reports/email-send-001/playwright',
  use:{baseURL:'http://127.0.0.1:18817',headless:true,channel:'msedge',trace:'retain-on-failure'},
  projects:[
    {name:'setup',testMatch:/auth\.setup\.ts/},
    {name:'chromium',testIgnore:/auth\.setup\.ts/,use:{storageState:'e2e/.auth/state.json'},dependencies:['setup']}
  ]
});
