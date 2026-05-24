/**
 * API 文档数据 —— 供 docs.vue 和 DocsEndpointCard 组件使用
 * 路由与 tg_imagebed/api/ 实际代码同步
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
          schema: 'file: (binary) 图片文件，支持 JPG/PNG/GIF/WebP/BMP/AVIF/TIFF/ICO',
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
        curlExample: `curl -X POST "<BASE_URL>/api/auth/upload" -H "Authorization: Bearer <token>" -F "file=@image.jpg"`,
      },
    ],
  },
  {
    id: 'token',
    title: 'Token 管理',
    description: '创建、验证、删除访问 Token，管理上传和访问权限。',
    icon: 'heroicons:key',
    endpoints: [
      {
        id: 'token-generate',
        method: 'POST',
        path: '/api/auth/token/generate',
        summary: '创建新 Token',
        description: '创建一个新的访问 Token，可设置权限、配额和有效期。需要 TG 登录或管理员权限。',
        auth: 'bearer',
        responses: [
          { status: 200, description: 'Token 创建成功，返回 Token 值' },
          { status: 400, description: '参数错误' },
          { status: 401, description: '未认证' },
        ],
      },
      {
        id: 'token-verify',
        method: 'POST',
        path: '/api/auth/token/verify',
        summary: '验证 Token',
        description: '验证一个 Token 是否有效及其剩余配额。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回 Token 验证结果和剩余配额' },
        ],
      },
      {
        id: 'token-manage',
        method: 'GET',
        path: '/api/auth/token',
        summary: '查询/修改/删除 Token',
        description: 'GET 查询当前用户的 Token 信息；PATCH 修改配置；DELETE 删除 Token。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '操作成功' },
          { status: 401, description: '未认证' },
          { status: 404, description: 'Token 不存在' },
        ],
      },
      {
        id: 'token-bind',
        method: 'POST',
        path: '/api/auth/token/bind',
        summary: '绑定 Token',
        description: '将已有 Token 绑定到当前 TG 账号。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '绑定成功' },
          { status: 400, description: 'Token 无效或已被绑定' },
        ],
      },
      {
        id: 'token-unbind',
        method: 'POST',
        path: '/api/auth/token/unbind',
        summary: '解绑 Token',
        description: '解除 Token 与当前 TG 账号的绑定。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '解绑成功' },
        ],
      },
    ],
  },
  {
    id: 'images',
    title: '图片查询与管理',
    description: '查询已上传的图片信息、上传历史，支持删除操作。',
    icon: 'heroicons:photo',
    endpoints: [
      {
        id: 'image-access',
        method: 'GET',
        path: '/image/<encrypted_id>',
        summary: '访问图片',
        description: '根据加密 ID 访问图片文件。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回图片二进制内容' },
          { status: 404, description: '图片不存在' },
        ],
      },
      {
        id: 'uploads-history',
        method: 'GET',
        path: '/api/auth/uploads',
        summary: '上传历史',
        description: '获取当前 Token 的上传历史记录。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '返回上传历史列表' },
          { status: 401, description: '未认证' },
        ],
      },
      {
        id: 'image-delete',
        method: 'DELETE',
        path: '/api/auth/images/<encrypted_id>',
        summary: '删除图片',
        description: '根据加密 ID 删除已上传的图片。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '删除成功' },
          { status: 404, description: '图片不存在或无权限' },
        ],
      },
      {
        id: 'images-batch-delete',
        method: 'POST',
        path: '/api/auth/images/batch-delete',
        summary: '批量删除图片',
        description: '批量删除多张已上传的图片。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '批量删除完成' },
        ],
      },
    ],
  },
  {
    id: 'galleries',
    title: '画集管理',
    description: '创建和管理个人画集，支持公开/私有/Token/密码访问模式。',
    icon: 'heroicons:rectangle-stack',
    endpoints: [
      {
        id: 'galleries-list',
        method: 'GET',
        path: '/api/auth/galleries',
        summary: '获取画集列表',
        description: '获取当前用户创建的所有画集。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '返回画集列表' },
          { status: 401, description: '未认证' },
        ],
      },
      {
        id: 'galleries-create',
        method: 'POST',
        path: '/api/auth/galleries',
        summary: '创建画集',
        description: '创建一个新画集，可设置名称、描述和访问模式。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '画集创建成功' },
          { status: 400, description: '参数错误' },
        ],
      },
      {
        id: 'gallery-manage',
        method: 'GET',
        path: '/api/auth/galleries/<id>',
        summary: '画集详情/修改/删除',
        description: 'GET 获取画集详情；PATCH 修改画集信息；DELETE 删除画集。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '操作成功' },
          { status: 404, description: '画集不存在' },
        ],
      },
      {
        id: 'gallery-images',
        method: 'GET',
        path: '/api/auth/galleries/<id>/images',
        summary: '画集图片管理',
        description: 'GET 获取画集内图片列表；POST 添加图片；DELETE 移除图片。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '操作成功' },
        ],
      },
      {
        id: 'gallery-cover',
        method: 'PUT',
        path: '/api/auth/galleries/<id>/cover',
        summary: '设置画集封面',
        description: '设置或删除画集的封面图片。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '封面更新成功' },
        ],
      },
      {
        id: 'gallery-share',
        method: 'POST',
        path: '/api/auth/galleries/<id>/share',
        summary: '生成/撤销分享链接',
        description: 'POST 生成画集分享链接；DELETE 撤销分享。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '操作成功，返回分享链接' },
        ],
      },
    ],
  },
  {
    id: 'shared',
    title: '共享画集访问',
    description: '通过分享链接访问他人画集，支持密码和 Token 解锁。',
    icon: 'heroicons:link',
    endpoints: [
      {
        id: 'shared-gallery',
        method: 'GET',
        path: '/api/shared/galleries/<share_token>',
        summary: '访问共享画集',
        description: '通过分享 Token 访问一个共享画集及其图片。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回画集信息' },
          { status: 403, description: '需要密码或 Token 解锁' },
          { status: 404, description: '分享不存在或已失效' },
        ],
      },
      {
        id: 'shared-unlock',
        method: 'POST',
        path: '/api/shared/galleries/<share_token>/unlock',
        summary: '密码解锁共享画集',
        description: '输入密码解锁受密码保护的共享画集。',
        auth: 'none',
        responses: [
          { status: 200, description: '解锁成功' },
          { status: 403, description: '密码错误' },
        ],
      },
      {
        id: 'shared-unlock-token',
        method: 'POST',
        path: '/api/shared/galleries/<share_token>/unlock-token',
        summary: 'Token 解锁共享画集',
        description: '使用访问 Token 解锁受 Token 保护的共享画集。',
        auth: 'bearer',
        responses: [
          { status: 200, description: '解锁成功' },
          { status: 403, description: 'Token 无效' },
        ],
      },
    ],
  },
  {
    id: 'status',
    title: '系统状态',
    description: '查询系统运行状态、存储统计和公开配置信息。',
    icon: 'heroicons:chart-bar',
    endpoints: [
      {
        id: 'health',
        method: 'GET',
        path: '/api/health',
        summary: '健康检查',
        description: '检查服务是否正常运行。',
        auth: 'none',
        responses: [
          { status: 200, description: '服务正常' },
        ],
        curlExample: `curl "<BASE_URL>/api/health"`,
      },
      {
        id: 'status-stats',
        method: 'GET',
        path: '/api/stats',
        summary: '获取系统统计',
        description: '返回系统存储用量、图片数量等公开统计数据。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回统计数据' },
        ],
      },
      {
        id: 'status-info',
        method: 'GET',
        path: '/api/info',
        summary: '获取系统信息',
        description: '返回系统版本和运行信息。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回系统信息' },
        ],
      },
      {
        id: 'recent',
        method: 'GET',
        path: '/api/recent',
        summary: '最近上传',
        description: '获取最近上传的公开图片列表。',
        auth: 'none',
        responses: [
          { status: 200, description: '返回最近图片列表' },
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
