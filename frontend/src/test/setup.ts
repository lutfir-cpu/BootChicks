import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

beforeEach(() => {
  // jsdom implements neither.
  Element.prototype.scrollIntoView = vi.fn()
  window.matchMedia = vi.fn((query: string) => ({ matches: false, media: query }) as MediaQueryList)
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})
