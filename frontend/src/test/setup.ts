import '@testing-library/jest-dom/vitest'

// jsdom has no ResizeObserver; React Flow uses one to size its canvas.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub
