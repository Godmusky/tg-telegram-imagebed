/**
 * API 文档数据 —— 供 docs.vue 和 DocsEndpointCard 组件使用
 */
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'

export interface ApiEndpoint {
  id: string
  method: HttpMethod
  path: string
  summary: string
  description?: string
  auth: 'none' | 'bearer' | 'token'
  requestBody?: {
    contentType: string
    schema: string
  }
  responses: Array<{
    status: number
    description: string
    example?: string
  }>
  curlExample?: string
}

export interface ApiSection {
  id: string
  title: string
  description: string
  icon: string
  endpoints: ApiEndpoint[]
}

export const apiSections: ApiSection[] = [
  {
    id: 'upload',
    title: '图片上传',
    description: '通过 POST 请求上传图片文件，支持匿名上传和 Token 认证两种模式。',
    icon: 'heroicons:cloud-arrow-up',
    endpoints: [
      {
        id: 'upload-anonymous',
        method: 'POST',
        path: '/api/upload',
        summary: '匿名上传图片',
        description: '无需认证即可上传图片，受系统匿名上传策略限制。若系统禁用匿名上传，返回 403。',
        auth: 'none',
        requestBody: {
          contentType: 'multipart/form-data',
          schema: 'file: (binary) 图片文件，支持 JPG/PNG/GIF/WebP/AVIF/SVG',
        },
        responses: [
          {
            status: 200,
            description: '上传成功，返回图片信息和访问 URL',
            example: JSON.stringify({ success: true, data: { url: 'https://...', filename: 'image.jpg' } }, null, 2),
          },
          { status: 400, description: '请求参数错误或文件格式不支持' },
          { status: 403, description: '匿名上传功能已被管理员禁用' },
          { status: 413, description: '上传文件体积超过限制' },
        ],
        curlExample: `curl -X POST "<BASE_URL>/api/upload" -F "file=@image.jpg"`,
      },
      {
        id: 'upload-token',
        method: 'POST',
        path: '/api/auth/upload',
        summary: 'Token 认证上传',
        description: '使用 Bearer Token 认证后上传，适合配额控制和访问审计。',
        auth: 'bearer',
        requestBody: {
          contentType: 'multipart/form-data',
          schema: 'file: (binary) 图片文件\nAuthorization: Bearer <token>',
        },
        responses: [
          {
            status: 200,
            description: '上传成功',
            example: JSON.stringify({ success: true, data: { url: 'https://...', filename: 'image.jpg' } }, null, 2),
          },
          { status: 401, description: 'Token 缺失、格式错误或已失效' },
          { status: 400, description: '请求参数错误' },
          { status: 413, description: '上传文件体积超过限制' },
        ],
        curlExample: `curl -X POST "<BASE_URL>/api/auth/upload" -H "Authorization: Bearer <TOKEN>" -F "file=@image.jpg"`,
      },
    ],
  },
  {
    id: 'images',
    title: '图片查询与管理',
    description: '查询已上传的图片信息、列表，支持分页、搜索和过滤。',
    icon: 'heroicons:photo',
    endpoints: [
      {
        id: 'images-list',
        method: 'GET',
        path: '/api/images',
        summary: '获取图片列表',
        description: '分页获取已上传的图片列表，支持分页参数。',
        auth: 'bearer',
        responses: [
          {
            status: 200,
            description: '返回图片列表和分页信息',
          },
          { status: 401, description: '未认证或 Token 无效' },
        ],
      },
      {
        id: 'image-detail',
        method: 'GET',
        path: '/api/image/:encrypted_id',
        summary: '获取图片详情',
        description: '根据加密 ID 获取图片的详细信息。',
        auth: 'none',
        responses: [
          {
            status: 200,
            description: '返回图片详细信息',
          },
          { status: 404, description: '图片不存在' },
        ],
      },
    ],
  },
  {
    id: 'tokens',
    title: 'Token 管理',
    description: '创建、查询、删除访问 Token，管理上传和访问权限。',
    icon: 'heroicons:key',
    endpoints: [
      {
        id: 'tokens-list',
        method: 'GET',
        path: '/api/tokens',
        summary: '获取 Token 列表',
        description: '获取当前用户创建的所有 Token 及其状态。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '返回 Token 列表' },
          { status: 401, description: '未认证' },
        ],
      },
      {
        id: 'tokens-create',
        method: 'POST',
        path: '/api/tokens',
        summary: '创建新 Token',
        description: '创建一个新的访问 Token，可设置权限、配额和有效期。',
        auth: 'bearer',
        responses: [
          { status: 200, description: 'Token 创建成功，返回 Token 值' },
          { status: 400, description: '参数错误' },
        ],
      },
      {
        id: 'tokens-delete',
        method: 'DELETE',
        path: '/api/tokens/:id',
        summary: '删除 Token',
        description: '删除指定的 Token，立即生效。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '删除成功' },
          { status: 404, description: 'Token 不存在' },
        ],
      },
    ],
  },
  {
    id: 'status',
    title: '系统状态',
    description: '查询系统运行状态、存储统计和配置信息。',
    icon: 'heroicons:chart-bar',
    endpoints: [
      {
        id: 'status-stats',
        method: 'GET',
        path: '/api/stats',
        summary: '获取系统统计信息',
        description: '返回系统存储用量、图片数量等统计数据。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回统计数据' },
        ],
      },
      {
        id: 'public-settings',
        method: 'GET',
        path: '/api/public/settings',
        summary: '获取公开配置',
        description: '获取站点名称、描述、SEO 配置等公开信息。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回公开配置信息' },
        ],
      },
    ],
  },
]

export function getMethodColor(method: HttpMethod): string {
  switch (method) {
    case 'GET':
      return 'blue'
    case 'POST':
      return 'green'
    case 'PUT':
      return 'amber'
    case 'DELETE':
      return 'red'
    case 'PATCH':
      return 'gray'
    default:
      return 'gray'
  }
}
