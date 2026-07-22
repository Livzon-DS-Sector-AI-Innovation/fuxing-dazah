/**
 * 检查用户权限集合是否匹配目标权限。
 * 支持通配符 * 匹配单层级。
 */
export function matchPermission(pattern: string, target: string): boolean {
  const patternParts = pattern.split(':')
  const targetParts = target.split(':')
  if (patternParts.length !== targetParts.length) return false
  return patternParts.every((part, i) => part === '*' || part === targetParts[i])
}

/**
 * 检查用户权限集合中是否有任意一个匹配目标模式。
 */
export function hasAnyPermission(
  userPermissions: Set<string>,
  patterns: string[],
): boolean {
  for (const pattern of patterns) {
    if (!pattern.includes('*')) {
      if (userPermissions.has(pattern)) return true
      continue
    }
    for (const perm of userPermissions) {
      if (matchPermission(pattern, perm)) return true
    }
  }
  return false
}
