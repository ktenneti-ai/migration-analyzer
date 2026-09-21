import type { Status, SqlTranslationStatus } from '../types/canonical'

// Reuses the app's CONFIRMED/INFERRED/REQUIRES_INPUT status grammar for the
// translator's finer-grained auto/auto_spot_check/needs_review/manual_port/
// unsupported scale, so the same visual language (StatusBadge) applies here.
const SQL_STATUS_TO_BADGE: Record<SqlTranslationStatus, Status> = {
  auto: 'CONFIRMED',
  auto_spot_check: 'INFERRED',
  needs_review: 'REQUIRES_INPUT',
  manual_port: 'REQUIRES_INPUT',
  unsupported: 'REQUIRES_INPUT',
}

export function sqlStatusToBadgeStatus(status: SqlTranslationStatus): Status {
  return SQL_STATUS_TO_BADGE[status] ?? 'REQUIRES_INPUT'
}
