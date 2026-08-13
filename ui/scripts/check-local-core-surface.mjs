#!/usr/bin/env node
/**
 * 本地精简内核前端表面检查
 *
 * 失败条件：保留的入口、路由、应用设置或 API 客户端中仍引用已删除的后端能力。
 * 不扫描：locales、静态资源目录、非源码文件。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, extname } from 'node:path'

const ROOT = new URL('../src/', import.meta.url).pathname
const SOURCE_EXT = new Set(['.ts', '.vue'])

const forbidden = [
  "name: 'trigger'",
  "router.push('/tool')",
  'getToolAggregation(',
  'importApplication(',
  'exportApplication(',
  '/text_to_speech',
  '/speech_to_text',
  '/play_demo_text',
  'SourceTypeEnum.TOOL',
  "resource: 'TOOL'",
]

const IGNORED_DIRS = new Set(['locales', 'assets', 'lang'])

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      if (IGNORED_DIRS.has(entry)) continue
      yield* walk(full)
    } else if (SOURCE_EXT.has(extname(full))) {
      yield full
    }
  }
}

let failed = false
for (const file of walk(ROOT)) {
  const lines = readFileSync(file, 'utf8').split('\n')
  lines.forEach((line, index) => {
    for (const pattern of forbidden) {
      if (line.includes(pattern)) {
        failed = true
        console.log(`${file}:${index + 1}  [${pattern}]`)
      }
    }
  })
}

if (failed) {
  console.error('FAIL: 保留前端表面仍引用已删除能力')
  process.exit(1)
}
console.log('PASS: 前端表面无已删除能力引用')