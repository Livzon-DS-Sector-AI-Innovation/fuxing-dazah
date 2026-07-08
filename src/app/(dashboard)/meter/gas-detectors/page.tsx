import { GasDetectorTable, CalibrationAlertPanel } from '@/components/meter'

export default function GasDetectorsPage() {
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16, fontSize: 18, fontWeight: 600 }}>有毒有害可燃探测器台账</h2>
      <GasDetectorTable />
      <CalibrationAlertPanel source="gas_detector" />
    </div>
  )
}
