'use client'

import { useEffect, useRef } from 'react'
import { usePermissionStore } from '@/stores/permission'
import { getCurrentUser } from '@/actions/auth'

const MAX_RETRIES = 3
const BASE_DELAY_MS = 1000

export function usePermission() {
  const { permissions, roles, dataScopes, isLoaded, loadError, hasPermission, setPermissionData, setLoadError, reset } =
    usePermissionStore()

  const retryCountRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    if (isLoaded || loadError) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const load = async () => {
      try {
        const user = await getCurrentUser()
        if (!mountedRef.current || cancelled) return

        if (user) {
          retryCountRef.current = 0
          setPermissionData({
            permissions: user.permissions ?? [],
            roles: user.roles ?? [],
            dataScopes: user.data_scopes ?? {},
          })
        } else {
          throw new Error('getCurrentUser 返回 null')
        }
      } catch {
        if (!mountedRef.current || cancelled) return
        retryCountRef.current += 1
        if (retryCountRef.current <= MAX_RETRIES) {
          const delay = BASE_DELAY_MS * Math.pow(2, retryCountRef.current - 1)
          timer = setTimeout(load, delay)
        } else {
          setLoadError()
        }
      }
    }

    load()
    return () => {
      cancelled = true
      if (timer !== null) clearTimeout(timer)
    }
  }, [isLoaded, loadError, setPermissionData, setLoadError])

  return { permissions, roles, dataScopes, isLoaded, hasPermission, reset }
}
