import Link from 'next/link'

export default function DashboardNotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-6 text-center">
      <p className="text-[56px] font-semibold leading-none text-[var(--color-primary)]">404</p>
      <h1 className="mt-4 text-[22px] font-semibold text-[var(--color-charcoal)]">
        页面不存在或功能尚未上线
      </h1>
      <p className="mt-2 max-w-md text-[14px] leading-6 text-[var(--color-steel)]">
        当前菜单对应的页面还未开放，你可以返回模块首页继续浏览其他功能。
      </p>
      <Link
        href="/welcome"
        className="mt-6 inline-flex h-9 items-center rounded-lg bg-[var(--color-primary)] px-4 text-[14px] font-medium text-white transition-opacity hover:opacity-90"
      >
        返回首页
      </Link>
    </div>
  )
}
