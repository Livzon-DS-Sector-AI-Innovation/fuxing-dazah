export default function CalculatorPage() {
  return (
    <div style={{ width: '100%', height: 'calc(100vh - 120px)' }}>
      <iframe
        src="/calculator.html"
        style={{ width: '100%', height: '100%', border: 'none' }}
        title="液相计算表"
      />
    </div>
  )
}
