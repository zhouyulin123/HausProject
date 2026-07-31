function normalizeSlideCount(slideCount: number): number {
  return Number.isFinite(slideCount) ? Math.max(0, Math.floor(slideCount)) : 0;
}

export function getNextSlideIndex(
  currentIndex: number,
  slideCount: number,
): number {
  const count = normalizeSlideCount(slideCount);
  if (count === 0) return 0;
  return (Math.max(0, Math.floor(currentIndex)) + 1) % count;
}

export function getPreviousSlideIndex(
  currentIndex: number,
  slideCount: number,
): number {
  const count = normalizeSlideCount(slideCount);
  if (count === 0) return 0;
  return (Math.max(0, Math.floor(currentIndex)) - 1 + count) % count;
}
