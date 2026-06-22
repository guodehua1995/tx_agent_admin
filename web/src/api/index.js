import { request } from '@/utils'

export default {
  login: (data) => request.post('/base/access_token', data, { noNeedToken: true }),
  getUserInfo: () => request.get('/base/userinfo'),
  getUserMenu: () => request.get('/base/usermenu'),
  getUserApi: () => request.get('/base/userapi'),
  // profile
  updatePassword: (data = {}) => request.post('/base/update_password', data),
  // users
  getUserList: (params = {}) => request.get('/user/list', { params }),
  getUserById: (params = {}) => request.get('/user/get', { params }),
  createUser: (data = {}) => request.post('/user/create', data),
  updateUser: (data = {}) => request.post('/user/update', data),
  deleteUser: (params = {}) => request.delete(`/user/delete`, { params }),
  resetPassword: (data = {}) => request.post(`/user/reset_password`, data),
  // role
  getRoleList: (params = {}) => request.get('/role/list', { params }),
  createRole: (data = {}) => request.post('/role/create', data),
  updateRole: (data = {}) => request.post('/role/update', data),
  deleteRole: (params = {}) => request.delete('/role/delete', { params }),
  updateRoleAuthorized: (data = {}) => request.post('/role/authorized', data),
  getRoleAuthorized: (params = {}) => request.get('/role/authorized', { params }),
  // menus
  getMenus: (params = {}) => request.get('/menu/list', { params }),
  createMenu: (data = {}) => request.post('/menu/create', data),
  updateMenu: (data = {}) => request.post('/menu/update', data),
  deleteMenu: (params = {}) => request.delete('/menu/delete', { params }),
  // apis
  getApis: (params = {}) => request.get('/api/list', { params }),
  createApi: (data = {}) => request.post('/api/create', data),
  updateApi: (data = {}) => request.post('/api/update', data),
  deleteApi: (params = {}) => request.delete('/api/delete', { params }),
  refreshApi: (data = {}) => request.post('/api/refresh', data),
  // depts
  getDepts: (params = {}) => request.get('/dept/list', { params }),
  createDept: (data = {}) => request.post('/dept/create', data),
  updateDept: (data = {}) => request.post('/dept/update', data),
  deleteDept: (params = {}) => request.delete('/dept/delete', { params }),
  // auditlog
  getAuditLogList: (params = {}) => request.get('/auditlog/list', { params }),
  // AI Config
  getAiConfigList: (params = {}) => request.get('/ai_config/list', { params }),
  getAiConfig: (params = {}) => request.get('/ai_config/get', { params }),
  createAiConfig: (data = {}) => request.post('/ai_config/create', data),
  updateAiConfig: (data = {}) => request.post('/ai_config/update', data),
  deleteAiConfig: (params = {}) => request.delete('/ai_config/delete', { params }),
  testAiConfig: (params = {}) => request.post('/ai_config/test', null, { params }),
  // Knowledge Base
  getKnowledgeBaseList: (params = {}) => request.get('/knowledge_base/list', { params }),
  getKnowledgeBase: (params = {}) => request.get('/knowledge_base/get', { params }),
  createKnowledgeBase: (data = {}) => request.post('/knowledge_base/create', data),
  updateKnowledgeBase: (data = {}) => request.post('/knowledge_base/update', data),
  deleteKnowledgeBase: (params = {}) => request.delete('/knowledge_base/delete', { params }),
  // Document Type (仅提供列表接口，供上传文档时选择)
  getDocumentTypeList: () => request.get('/document/type/list'),
  // Document
  getDocumentList: (params = {}) => request.get('/document/list', { params }),
  getDocument: (params = {}) => request.get('/document/get', { params }),
  createDocument: (data = {}) => request.post('/document/create', data),
  updateDocument: (data = {}) => request.post('/document/update', data),
  deleteDocument: (params = {}) => request.delete('/document/delete', { params }),
  retryDocument: (params = {}) => request.post('/document/retry', null, { params }),
  updateDocumentContent: (data = {}) => request.post('/document/update_content', data),
  // Agent
  getAgentList: (params = {}) => request.get('/agent/list', { params }),
  getAgent: (params = {}) => request.get('/agent/get', { params }),
  createAgent: (data = {}) => request.post('/agent/create', data),
  updateAgent: (data = {}) => request.post('/agent/update', data),
  deleteAgent: (params = {}) => request.delete('/agent/delete', { params }),
  updateAgentKnowledgeBases: (data = {}) => request.post('/agent/update_knowledge_bases', data),
  agentChat: (data = {}) => request.post('/agent/chat', data),
  agentChatStream: (data = {}) =>
    request.post('/agent/chat/stream', data, {
      responseType: 'text',
      headers: {
        Accept: 'text/event-stream',
      },
    }),
  // Review
  getReviewList: (params = {}) => request.get('/review/list', { params }),
  getReview: (params = {}) => request.get('/review/get', { params }),
  getReviewHistory: (params = {}) => request.get('/review/history', { params }),
  approveReview: (data = {}) => request.post('/review/approve', data),
  rejectReview: (data = {}) => request.post('/review/reject', data),
  // Feishu Bot
  getFeishuBotList: (params = {}) => request.get('/feishu/bot/list', { params }),
  getFeishuBot: (params = {}) => request.get('/feishu/bot/get', { params }),
  createFeishuBot: (data = {}) => request.post('/feishu/bot/create', data),
  updateFeishuBot: (data = {}) => request.post('/feishu/bot/update', data),
  deleteFeishuBot: (params = {}) => request.delete('/feishu/bot/delete', { params }),
  // Feishu Folder Watch (飞书文件夹监听)
  getFeishuFolderList: (params = {}) => request.get('/feishu_folder/list', { params }),
  getFeishuFolder: (params = {}) => request.get('/feishu_folder/get', { params }),
  createFeishuFolder: (data = {}) => request.post('/feishu_folder/create', data),
  updateFeishuFolder: (data = {}) => request.post('/feishu_folder/update', data),
  toggleFeishuFolder: (data = {}) => request.post('/feishu_folder/toggle', data),
  deleteFeishuFolder: (params = {}) => request.delete('/feishu_folder/delete', { params }),
  scanFeishuFolderNow: (params = {}) => request.post('/feishu_folder/scan_now', null, { params }),
  getFeishuFolderFiles: (params = {}) => request.get('/feishu_folder/files', { params }),
  cleanupFeishuFolderFile: (params = {}) => request.post('/feishu_folder/files/cleanup', null, { params }),
  // Doc Template
  getDocTemplateList: (params = {}) => request.get('/doc_template/list', { params }),
  getDocTemplate: (params = {}) => request.get('/doc_template/get', { params }),
  createDocTemplate: (data = {}) => request.post('/doc_template/create', data),
  updateDocTemplate: (data = {}) => request.post('/doc_template/update', data),
  deleteDocTemplate: (params = {}) => request.delete('/doc_template/delete', { params }),
  parseDocTemplateUrl: (data = {}) => request.post('/doc_template/parse_url', data, {timeout: 600000}),
  getDocTemplateOptions: () => request.get('/doc_template/options'),
  generateDoc: (data = {}) => request.post('/doc_template/generate', data),
  // Conversation
  getConversationList: (params = {}) => request.get('/feishu/conversations', { params }),
  getMessageList: (params = {}) => request.get('/feishu/messages', { params }),
  // Dashboard
  getDashboardStats: () => request.get('/dashboard/stats'),
  getDashboardTrends: () => request.get('/dashboard/trends'),
  // Global Config
  getGlobalConfigList: (params = {}) => request.get('/global_config/list', { params }),
  getGlobalConfigGrouped: () => request.get('/global_config/grouped'),
  getGlobalConfig: (params = {}) => request.get('/global_config/get', { params }),
  createGlobalConfig: (data = {}) => request.post('/global_config/create', data),
  updateGlobalConfig: (data = {}) => request.post('/global_config/update', data),
  batchUpdateGlobalConfig: (data = {}) => request.post('/global_config/batch_update', data),
  deleteGlobalConfig: (params = {}) => request.delete('/global_config/delete', { params }),
  // KB Content (知识库内容管理)
  getKBContentList: (params = {}) => request.get('/kb_content/list', { params }),
  createKBContentDoc: (data = {}) => request.post('/kb_content/create', data),
  deleteKBContentDoc: (params = {}) => request.delete('/kb_content/delete', { params }),
  // Doc Content (文档切片管理)
  getDocChunkList: (params = {}) => request.get('/doc_content/list', { params }),
  createDocChunk: (data = {}) => request.post('/doc_content/create', data),
  updateDocChunk: (data = {}) => request.post('/doc_content/update', data),
  deleteDocChunk: (params = {}) => request.delete('/doc_content/delete', { params }),
  // Doc Pages (文档分页管理)
  getDocPages: (params = {}) => request.get('/doc_page/list', { params }),
  getDocPageDetail: (params = {}) => request.get('/doc_page/detail', { params }),
  updateDocPageContent: (data = {}) => request.post('/doc_page/update_content', data),
}
