'use client'

import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeRaw from 'rehype-raw'

interface AIReportPanelProps {
  content: string
}

function safeSlice(text: string, length: number): string {
  if (length >= text.length) return text
  let end = length

  const lastLt = text.lastIndexOf('<', end - 1)
  const lastGt = text.lastIndexOf('>', end - 1)
  if (lastLt > lastGt) {
    end = lastLt
  }

  const lastAmp = text.lastIndexOf('&', end - 1)
  const lastSemi = text.lastIndexOf(';', end - 1)
  if (lastAmp > lastSemi) {
    end = lastAmp
  }

  return text.slice(0, end)
}

export default function AIReportPanel({ content }: AIReportPanelProps) {
  const [phase, setPhase] = useState<'thinking' | 'streaming' | 'done'>('thinking')
  const [displayLength, setDisplayLength] = useState(0)

  useEffect(() => {
    const timer = setTimeout(() => setPhase('streaming'), 3000)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (phase !== 'streaming') return
    let current = 0
    const interval = setInterval(() => {
      current += 1
      if (current >= content.length) {
        clearInterval(interval)
        setDisplayLength(content.length)
        setPhase('done')
      } else {
        setDisplayLength(current)
      }
    }, 50)
    return () => clearInterval(interval)
  }, [phase, content])

  const visibleText = safeSlice(content, displayLength)

  return (
    <div className="bg-gray-50 rounded-lg p-4 text-sm leading-relaxed prose prose-sm max-w-none min-h-[120px]">
      {phase !== 'done' && (
        <div className={`flex items-center gap-2 mb-3 ${phase === 'thinking' ? 'flex-col justify-center py-6' : ''}`}>
          <div className={`relative ${phase === 'thinking' ? 'w-12 h-12' : 'w-8 h-8'}`}>
            <div
              className="absolute inset-0 rounded-full animate-spin"
              style={{
                background:
                  'conic-gradient(from 0deg, transparent, #1677ff, #00b4ff, transparent)',
              }}
            />
            <div
              className={`absolute bg-gray-50 rounded-full ${phase === 'thinking' ? 'inset-1' : 'inset-[2px]'}`}
            />
          </div>
          <span className="text-gray-500 text-sm">深度思考中</span>
        </div>
      )}

      {(phase === 'streaming' || phase === 'done') && (
        <ReactMarkdown rehypePlugins={[rehypeRaw]}>
          {visibleText}
        </ReactMarkdown>
      )}

      {phase === 'streaming' && (
        <span className="inline-block w-[2px] h-4 bg-blue-500 align-middle ml-0.5 animate-pulse" />
      )}
    </div>
  )
}
