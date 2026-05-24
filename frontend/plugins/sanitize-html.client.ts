/**
 * DOMPurify 白名单消毒插件
 *
 * 对 v-html 渲染的内容进行白名单过滤，防御 XSS。
 * 允许常用格式化标签，禁止 <script> <iframe> on* 事件属性等危险内容。
 */

import DOMPurify from 'dompurify'

const ALLOWED_TAGS = [
  // 标题
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  // 段落与文本
  'p', 'br', 'hr', 'strong', 'em', 'b', 'i', 'u', 's', 'del', 'ins',
  'sub', 'sup', 'mark', 'small', 'code', 'pre',
  // 列表
  'ul', 'ol', 'li',
  // 链接
  'a',
  // 表格
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
  // 媒体（img 已移除 — 防止外部追踪像素泄露访客 IP/UA/阅读行为）
  'video', 'audio', 'source',
  // 布局
  'div', 'span', 'section', 'article', 'header', 'footer', 'nav', 'main',
  'blockquote', 'figure', 'figcaption',
  // 样式容器（模板中使用）
  'details', 'summary',
]

const ALLOWED_ATTR = [
  // 全局属性
  'class', 'id', 'style', 'title', 'lang', 'dir',
  // 链接
  'href', 'target', 'rel', 'download',
  // 图片/媒体
  'src', 'alt', 'width', 'height', 'loading',
  // 表格
  'colspan', 'rowspan',
  // 控件（只读）
  'type', 'controls',
  // 无障碍
  'aria-label', 'aria-hidden', 'role',
]

const SANITIZE_CONFIG: DOMPurify.Config = {
  ALLOWED_TAGS,
  ALLOWED_ATTR,
  ALLOW_DATA_ATTR: false,
  // 禁止所有事件处理器 (onclick, onerror, onload 等)
  // DOMPurify 默认已移除所有事件属性，此处显式声明以明确意图
  FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'select', 'textarea', 'style', 'link', 'meta'],
  FORBID_ATTR: [
    // 事件处理器虽然已被白名单排除，但显式 FORBID 更安全
    'onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur',
    'onchange', 'onsubmit', 'onkeydown', 'onkeyup', 'onkeypress',
    // 危险 URL 协议
  ],
  // 仅允许安全链接协议
  ALLOWED_URI_REGEXP: /^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
  // 返回字符串，清理 null 字节等
  RETURN_DOM: false,
  RETURN_DOM_FRAGMENT: false,
  RETURN_DOM_IMPORT: false,
  // 不移除整个内容，而是保留安全部分
  SANITIZE_DOM: true,
}

export default defineNuxtPlugin(() => {
  function sanitizeHtml(dirty: string): string {
    if (!dirty || typeof dirty !== 'string') return ''
    return DOMPurify.sanitize(dirty, SANITIZE_CONFIG)
  }

  return {
    provide: {
      sanitizeHtml,
    },
  }
})
