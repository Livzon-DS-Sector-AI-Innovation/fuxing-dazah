/** Business Agent (业务 Agent) 前端类型。 */

/** 后端 POST /safety/agent/chat 返回的 pending_action */
export interface AgentPendingAction {
  tool_name: string
  arguments: Record<string, unknown>
  summary: string
  status: string
}

/** POST /safety/agent/chat 的请求体 */
export interface AgentChatRequest {
  message: string
  session_id?: string
}

/** Agent 检索到的知识库法规来源（RAG sources） */
export interface AgentChatSource {
  doc_title: string
  article_ref: string
  chunk_text: string
  doc_category: string
  feishu_url: string
}

/** POST /safety/agent/chat 的响应 data */
export interface AgentChatResponse {
  session_id: string
  answer: string
  pending_action_id: string | null
  pending_action: AgentPendingAction | null
  sources: AgentChatSource[] | null
}

/** GET /safety/agent/sessions/{id} 的响应 data */
export interface AgentSessionInfo {
  id: string
  channel: string
  title: string | null
  message_count: number
  role: string | null
  last_active_at: string | null
}

/** POST /safety/agent/actions/{id}/confirm 的响应 data */
export interface AgentActionConfirmResponse {
  session_id: string
  answer: string
  executed: boolean
}
