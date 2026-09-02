import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const frontendDirectory = resolve(scriptDirectory, '..')
const projectDirectory = resolve(frontendDirectory, '..')
const buildDirectory = join(frontendDirectory, 'static-review-build')
const deliveryDirectory = join(projectDirectory, '交付文件')
const outputDirectory = join(deliveryDirectory, 'xinjian-four-html-review-2026-08-21')
const zipPath = `${outputDirectory}.zip`
const legacyOutputDirectory = join(
  deliveryDirectory,
  '芯鉴知微_四页面HTML审核包_2026-08-21',
)
const legacyZipPath = `${legacyOutputDirectory}.zip`

execFileSync(
  join(frontendDirectory, 'node_modules', '.bin', 'vite'),
  ['build', '--config', 'vite.static-review.config.ts', '--mode', 'review'],
  { cwd: frontendDirectory, stdio: 'inherit' },
)

const sourceHtml = readFileSync(join(buildDirectory, 'index.html'), 'utf8')
const scriptMatch = sourceHtml.match(/<script[^>]+src="([^"]+)"[^>]*><\/script>/)
const styleMatch = sourceHtml.match(/<link[^>]+href="([^"]+\.css)"[^>]*>/)

if (!scriptMatch || !styleMatch) {
  throw new Error('静态审核构建产物缺少脚本或样式文件。')
}

const resolveBuildAsset = (reference) =>
  join(buildDirectory, reference.replace(/^\.\//, ''))

let applicationScript = readFileSync(resolveBuildAsset(scriptMatch[1]), 'utf8')
const applicationStyle = readFileSync(resolveBuildAsset(styleMatch[1]), 'utf8')

const loginImagePath = join(frontendDirectory, 'public', 'assets', 'login-chip-platform.png')
const loginImageData = `data:image/png;base64,${readFileSync(loginImagePath).toString('base64')}`
applicationScript = applicationScript.replaceAll(
  '"assets/login-chip-platform.png"',
  JSON.stringify(loginImageData),
)

const safeScript = applicationScript.replaceAll('</script', '<\\/script')
const safeStyle = applicationStyle.replaceAll('</style', '<\\/style')

const pages = [
  ['01-student-login.html', '/login', '学生端登录'],
  ['02-student-dashboard.html', '/student', '学生端工作台'],
  ['03-teacher-login.html', '/teacher/login', '教师端登录'],
  ['04-teacher-dashboard.html', '/teacher', '教师端工作台'],
]

rmSync(legacyOutputDirectory, { recursive: true, force: true })
rmSync(legacyZipPath, { force: true })
rmSync(outputDirectory, { recursive: true, force: true })
mkdirSync(outputDirectory, { recursive: true })

for (const [filename, route, pageTitle] of pages) {
  const html = `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="芯鉴知微四页面前端静态审核稿，内置合成测试数据" />
    <link rel="icon" href="data:," />
    <title>芯鉴知微 · ${pageTitle}</title>
    <style>${safeStyle}</style>
    <script>
      if (!location.hash) location.replace(location.href + '#${route}')
    </script>
  </head>
  <body>
    <div id="app"></div>
    <script type="module">${safeScript}</script>
  </body>
</html>
`
  writeFileSync(join(outputDirectory, filename), html)
}

writeFileSync(
  join(outputDirectory, 'README-CN.txt'),
  `芯鉴知微四页面 HTML 审核包

使用方法：
1. 解压 ZIP。
2. 直接双击任意 .html 文件即可打开。
3. 不需要安装 Node.js、Python，也不需要启动后端或本地服务器。

页面：
- 01-student-login.html
- 02-student-dashboard.html（内置 4 条测试日志、22 条传感器读数与诊断示例）
- 03-teacher-login.html
- 04-teacher-dashboard.html（内置教师端审核数据）

说明：
- 所有数据均为前端内置合成测试数据。
- 页面不会访问后端、数据库或外部 AI 服务。
- 登录页可输入任意非空内容体验页面跳转。
`,
)

rmSync(zipPath, { force: true })
execFileSync(
  'zip',
  ['-q', '-X', '-r', zipPath, basename(outputDirectory)],
  { cwd: deliveryDirectory },
)
rmSync(buildDirectory, { recursive: true, force: true })

console.log(`HTML 审核包：${outputDirectory}`)
console.log(`ZIP：${zipPath}`)
console.log(`页面数量：${pages.length}`)
console.log(`单页入口：${pages.map(([name]) => basename(name)).join('、')}`)
