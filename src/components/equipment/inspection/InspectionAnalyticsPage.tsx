'use client'

import { TrendSection } from './TrendSection'
import { AnomalySection } from './AnomalySection'

// ── DESIGN.md tokens ──
// hero-band-dark: brand-navy(#0a1530) bg, on-dark text, primary(#5645d4) accent
// surface: #f6f5f4 页面底色

export function InspectionAnalyticsPage() {
  return (
    <div style={{ background: '#f6f5f4', minHeight: '100vh' }}>
      {/* ── hero-band-dark header ── */}
      <div style={{ background: '#0a1530', padding: '20px 32px', borderBottom: '3px solid #5645d4' }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>
          Inspection Analytics
        </div>
        <div style={{ fontSize: 22, fontWeight: 600, color: '#ffffff' }}>
          巡检数据分析
        </div>
      </div>

      {/* ── 内容区 ── */}
      <div style={{ margin: '0 auto', padding: '40px 0px' }}>
        <TrendSection />
        <AnomalySection />
      </div>
    </div>
  )
}
