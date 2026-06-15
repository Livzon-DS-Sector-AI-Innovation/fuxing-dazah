import { create } from 'zustand'
import { ChatMessage, HrPageContext, streamChat } from '@/lib/api/ai'

interface HrChatState {
  messages: ChatMessage[]
  isOpen: boolean
  isLoading: boolean
  inputValue: string
  pageContext: HrPageContext | null

  toggleOpen: () => void
  setOpen: (open: boolean) => void
  setInputValue: (value: string | ((prev: string) => string)) => void
  setPageContext: (ctx: HrPageContext | null) => void
  sendMessage: (content: string) => Promise<void>
  clearMessages: () => void
}

export const useHrChatStore = create<HrChatState>((set, get) => ({
  messages: [
    {
      role: 'assistant',
      content:
        '你好！我是 HR 智能助手「小H」。\n你可以问我关于员工数据查询、整理分析或人事管理建议的问题。',
    },
  ],
  isOpen: true,
  isLoading: false,
  inputValue: '',
  pageContext: null,

  toggleOpen: () => set((state) => ({ isOpen: !state.isOpen })),
  setOpen: (open) => set({ isOpen: open }),
  setInputValue: (value: string | ((prev: string) => string)) =>
    set((state) => ({
      inputValue:
        typeof value === 'function'
          ? (value as (prev: string) => string)(state.inputValue)
          : value,
    })),
  setPageContext: (ctx) => set({ pageContext: ctx }),

  sendMessage: async (content: string) => {
    if (!content.trim()) return

    const { messages, pageContext } = get()
    const userMsg: ChatMessage = { role: 'user', content: content.trim() }
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }

    set({
      messages: [...messages, userMsg, assistantMsg],
      isLoading: true,
      inputValue: '',
    })

    const allMessages = [...messages, userMsg]

    await streamChat(
      allMessages,
      pageContext,
      (type: string, text: string) => {
        set((state) => {
          const msgs = state.messages.map((msg, idx) => {
            if (idx === state.messages.length - 1 && msg.role === 'assistant') {
              if (type === 'reasoning') {
                return {
                  ...msg,
                  reasoning_content: (msg.reasoning_content || '') + text,
                }
              }
              return { ...msg, content: msg.content + text }
            }
            return msg
          })
          return { messages: msgs }
        })
      },
      () => {
        set({ isLoading: false })
      },
      (err) => {
        set((state) => {
          const last = state.messages[state.messages.length - 1]
          const hasEmptyAssistant = last?.role === 'assistant' && last?.content === ''
          const msgs = hasEmptyAssistant
            ? state.messages.slice(0, -1)
            : [...state.messages]
          return {
            messages: [
              ...msgs,
              { role: 'assistant', content: `[系统错误] ${err.message}` },
            ],
            isLoading: false,
          }
        })
      },
    )
  },

  clearMessages: () =>
    set({
      messages: [
        {
          role: 'assistant',
          content:
            '对话已清空。我是 HR 智能助手「小H」，有什么可以帮你的？',
        },
      ],
    }),
}))
