export function getRevealProgress(
  elapsedSeconds: number,
  delaySeconds: number,
  durationSeconds: number,
): number {
  if (durationSeconds <= 0) return elapsedSeconds >= delaySeconds ? 1 : 0;
  const linear = Math.min(1, Math.max(0, (elapsedSeconds - delaySeconds) / durationSeconds));
  return linear * linear * (3 - 2 * linear);
}

export function getScanPosition(
  elapsedSeconds: number,
  span: number,
  durationSeconds: number,
): number {
  if (span <= 0 || durationSeconds <= 0) return 0;
  const cycle = ((elapsedSeconds % durationSeconds) + durationSeconds) % durationSeconds;
  return -span / 2 + (cycle / durationSeconds) * span;
}

export type SpatialParticleVolume = {
  width: number;
  depth: number;
  height: number;
  centerX?: number;
  centerZ?: number;
  padding?: number;
};

const DEFAULT_PARTICLE_VOLUME: SpatialParticleVolume = {
  width: 12,
  depth: 12,
  height: 3.2,
};

export function createSpatialParticles(
  count: number,
  seed = 1,
  volume: SpatialParticleVolume = DEFAULT_PARTICLE_VOLUME,
): number[] {
  let state = seed >>> 0;
  const random = () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };

  const width = Math.max(0, volume.width);
  const depth = Math.max(0, volume.depth);
  const height = Math.max(0, volume.height);
  const centerX = volume.centerX ?? 0;
  const centerZ = volume.centerZ ?? 0;
  const padding = Math.max(0, volume.padding ?? 0);

  return Array.from({ length: Math.max(0, count) * 3 }, (_, index) => {
    const axis = index % 3;
    if (axis === 0) return centerX + (random() - 0.5) * (width + padding * 2);
    if (axis === 1) return 0.08 + random() * height;
    return centerZ + (random() - 0.5) * (depth + padding * 2);
  });
}
