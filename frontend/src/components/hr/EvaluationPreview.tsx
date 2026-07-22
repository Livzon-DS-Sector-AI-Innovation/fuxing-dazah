'use client'

interface Props {
  topicStr: string; dateStr: string; trainingMethodValue: string
  trainerValue: string; assessmentMethodValue: string; deptValue: string
  traineeDepts: string[]; previewNames: any[]; evalDurationHours: string | number | undefined
}

const R = { border:'1px solid #666', padding:'4px 8px', fontSize:12, lineHeight:1.5 } as const
const H = { ...R, background:'#e8e8e8', fontWeight:600, textAlign:'center' as const, width:'10%' }

export default function EvaluationPreview(p: Props) {
  const names = p.previewNames?.length || 0
  return (
    <div>
      <div className="text-xs text-gray-500 mb-1">QR.SOP.PM.003/18（格式） P8/12</div>
      <div className="text-center text-lg font-bold mb-1">丽珠集团福州福兴医药有限公司</div>
      <div className="text-center text-xl font-bold mb-4">培训效果评估表</div>
      <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
        <colgroup>
          <col style={{width:'8%'}} /><col style={{width:'8%'}} /><col style={{width:'7%'}} />
          <col style={{width:'7%'}} /><col style={{width:'5%'}} /><col style={{width:'7%'}} />
          <col style={{width:'7%'}} /><col style={{width:'7%'}} /><col style={{width:'5%'}} />
          <col style={{width:'7%'}} /><col style={{width:'7%'}} /><col style={{width:'7%'}} />
          <col style={{width:'6%'}} /><col style={{width:'6%'}} /><col style={{width:'3%'}} />
          <col style={{width:'3%'}} />
        </colgroup>
        <tbody>
          <tr><td style={H} colSpan={15}>培训内容 Training content</td></tr>
          <tr><td style={R} colSpan={15}>{p.topicStr || '___'}</td></tr>
          <tr>
            <td style={H} colSpan={8}>培训日期 Training date</td>
            <td style={H} colSpan={7}>课 时 Hours</td>
          </tr>
          <tr>
            <td style={R} colSpan={8}>{p.dateStr || '___'}</td>
            <td style={R} colSpan={7}>{String(p.evalDurationHours || '___')}</td>
          </tr>
          <tr>
            <td style={H} colSpan={8}>培训方式 Training method</td>
            <td style={H} colSpan={7}>培训师 Trainer</td>
          </tr>
          <tr>
            <td style={R} colSpan={8}>{p.trainingMethodValue || '___'}</td>
            <td style={R} colSpan={7}>{p.trainerValue || '___'}</td>
          </tr>
          <tr><td style={H} colSpan={15}>培训教材 Training materials</td></tr>
          <tr><td style={R} colSpan={15}>{p.deptValue || '___'}</td></tr>
          <tr><td style={H} colSpan={15}>培训对象 Trainees · 部门/班组/人员：{p.traineeDepts.join('、') || p.deptValue || '___'}</td></tr>
          <tr>
            <td style={H} colSpan={2}>应到人数</td><td style={R} colSpan={4}>{names}</td>
            <td style={H} colSpan={2}>实到人数</td><td style={R} colSpan={7}>___</td>
          </tr>
          <tr>
            <td style={H} colSpan={2}>缺席原因</td>
            <td style={H} colSpan={2}>事假</td><td style={R} colSpan={2}>___</td>
            <td style={H} colSpan={2}>病假</td><td style={R} colSpan={3}>___</td>
            <td style={H} colSpan={2}>产假</td><td style={R} colSpan={2}>___</td>
          </tr>
          <tr>
            <td style={H} colSpan={5}>考核方式 Assessment method</td>
            <td style={R} colSpan={5}>{p.assessmentMethodValue || '___'}</td>
            <td style={H} colSpan={3}>参加考核人数</td>
            <td style={R} colSpan={2}>{names}</td>
          </tr>
          <tr><td style={H} colSpan={15}>缺席人员处理方式：返岗一周内组织再培训并考核</td></tr>
          <tr>
            <td style={H} colSpan={5}>评价标准</td>
            <td style={R} colSpan={5}>优 ≥90</td>
            <td style={R} colSpan={5}>合格 ≥80且＜90 &nbsp; 不合格 ＜80</td>
          </tr>
          <tr>
            <td style={H} colSpan={5}>考核结果</td>
            <td style={H} colSpan={2}>优</td><td style={R} colSpan={3}>___</td>
            <td style={H} colSpan={2}>合格</td><td style={R} colSpan={3}>___</td>
          </tr>
          <tr>
            <td style={H} colSpan={5}></td>
            <td style={H} colSpan={2}>不合格</td><td style={R} colSpan={3}>___</td>
            <td style={H} colSpan={2}>缺考</td><td style={R} colSpan={3}>___</td>
          </tr>
          {['第一次','第二次','第三次'].map(label => (
            <tr key={label}>
              <td style={H} colSpan={5}>{label}补考结果</td>
              <td style={H} colSpan={2}>优</td><td style={R} colSpan={3}>—</td>
              <td style={H} colSpan={2}>合格</td><td style={R} colSpan={3}>—</td>
            </tr>
          ))}
          <tr><td style={H} colSpan={15}>培训效果总结：参与率 ___%，合格率 ___%</td></tr>
          <tr><td style={H} colSpan={15}>备注 Remark：——</td></tr>
        </tbody>
      </table>
    </div>
  )
}
