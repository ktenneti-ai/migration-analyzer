import type { ComplexityBand } from '../types/canonical'
import type { ComplexityLevel } from '../components/ui/ComplexityBadge'

// Mirrors backend/app/parsers/dax/classifier.py's complexity_bucket().
const BAND_TO_BUCKET: Record<ComplexityBand, ComplexityLevel> = {
  AUTO: 'LOW',
  AUTO_SPOT_CHECK: 'LOW',
  NEEDS_REVIEW: 'MEDIUM',
  MANUAL_PORT: 'HIGH',
  UNSUPPORTED: 'HIGH',
}

export function bandToBucket(band: ComplexityBand): ComplexityLevel {
  return BAND_TO_BUCKET[band] ?? 'HIGH'
}
