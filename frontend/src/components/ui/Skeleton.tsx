export function Skeleton({ width = '100%', height = 14 }: { width?: string | number; height?: number }) {
  return <div className="skeleton" style={{ width, height }} />
}

export function SkeletonStack({ rows = 4 }: { rows?: number }) {
  return (
    <div className="skeleton-stack">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} width={i === rows - 1 ? '60%' : '100%'} />
      ))}
    </div>
  )
}
