// Small hand-rolled line icons — no icon library dependency. Each is a plain
// 18x18 stroke glyph so they stay visually consistent as a set.
import type { SVGProps } from 'react'

function base(props: SVGProps<SVGSVGElement>) {
  return {
    width: 17,
    height: 17,
    viewBox: '0 0 18 18',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.4,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
    ...props,
  }
}

export const IconDashboard = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <rect x="2.5" y="2.5" width="6" height="6" />
    <rect x="9.5" y="2.5" width="6" height="9" />
    <rect x="2.5" y="10.5" width="6" height="5" />
  </svg>
)

export const IconProjects = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M2.5 4.5h4l1.2 1.6h7.8v7.4a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-9z" />
  </svg>
)

export const IconPowerBI = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <rect x="3" y="9" width="2.6" height="6" />
    <rect x="7.7" y="5.5" width="2.6" height="9.5" />
    <rect x="12.4" y="2.5" width="2.6" height="12.5" />
  </svg>
)

export const IconTeradata = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <ellipse cx="9" cy="4" rx="6" ry="2" />
    <path d="M3 4v10c0 1.1 2.7 2 6 2s6-.9 6-2V4" />
    <path d="M3 9c0 1.1 2.7 2 6 2s6-.9 6-2" />
  </svg>
)

export const IconLineage = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <circle cx="3.2" cy="4" r="1.6" />
    <circle cx="14.8" cy="4" r="1.6" />
    <circle cx="9" cy="9.5" r="1.6" />
    <circle cx="9" cy="15" r="1.6" />
    <path d="M4.5 5L7.8 8.3M13.5 5L10.2 8.3M9 11V13.4" />
  </svg>
)

export const IconGaps = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M9 2.5L16 15H2z" />
    <path d="M9 7v3.4" />
    <circle cx="9" cy="12.6" r="0.15" fill="currentColor" stroke="none" />
  </svg>
)

export const IconDatabricks = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M2.5 5L9 2.5 15.5 5 9 7.5 2.5 5z" />
    <path d="M2.5 9L9 6.5 15.5 9 9 11.5 2.5 9z" />
    <path d="M2.5 13L9 10.5 15.5 13 9 15.5 2.5 13z" />
  </svg>
)

export const IconSql = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M2.5 5.5h13M2.5 9h9M2.5 12.5h11" />
  </svg>
)

export const IconPlan = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <circle cx="4" cy="4" r="1.5" />
    <circle cx="4" cy="9" r="1.5" />
    <circle cx="4" cy="14" r="1.5" />
    <path d="M7 4h8M7 9h8M7 14h8" />
  </svg>
)

export const IconValidation = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M9 2.5l6 2v4.3c0 3.5-2.4 6.2-6 6.7-3.6-.5-6-3.2-6-6.7V4.5l6-2z" />
    <path d="M6.3 9l1.9 1.9 3.5-3.9" />
  </svg>
)

export const IconReport = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M4.5 2.5h6l3 3v10a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1z" />
    <path d="M6.5 9h5M6.5 11.7h5M6.5 6.3h2.5" />
  </svg>
)

export const IconExports = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M9 2.5v8M6 7.5L9 10.5 12 7.5" />
    <path d="M3.5 12v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" />
  </svg>
)

export const IconSettings = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <circle cx="9" cy="9" r="2.4" />
    <path d="M9 2.8v1.6M9 13.6v1.6M15.2 9h-1.6M4.4 9H2.8M13.2 4.8l-1.1 1.1M5.9 12.1l-1.1 1.1M13.2 13.2l-1.1-1.1M5.9 5.9 4.8 4.8" />
  </svg>
)

export const IconChevronLeft = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)} width={14} height={14}>
    <path d="M11 3.5L6 9l5 5.5" />
  </svg>
)

export const IconRefresh = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M14.5 9a5.5 5.5 0 1 1-1.8-4.1" />
    <path d="M14.5 2.5v3.5H11" />
  </svg>
)

export const IconSun = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <circle cx="9" cy="9" r="3" />
    <path d="M9 2v1.6M9 14.4V16M16 9h-1.6M3.6 9H2M13.7 4.3l-1.1 1.1M5.4 12.6l-1.1 1.1M13.7 13.7l-1.1-1.1M5.4 5.4 4.3 4.3" />
  </svg>
)

export const IconMoon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M14.5 10.4A5.6 5.6 0 0 1 7.6 3.5a5.6 5.6 0 1 0 6.9 6.9z" />
  </svg>
)
