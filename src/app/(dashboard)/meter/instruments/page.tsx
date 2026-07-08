import { InstrumentTable, CalibrationAlertPanel } from '@/components/meter'

export default function InstrumentsPage() {
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16, fontSize: 18, fontWeight: 600 }}>标准计量器具台账</h2>
      <InstrumentTable />
      <CalibrationAlertPanel source="instrument" />
    </div>
  )
}
