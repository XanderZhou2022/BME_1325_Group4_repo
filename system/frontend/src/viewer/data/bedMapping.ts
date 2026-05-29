import { DEMO_BED_IDS, DEMO_MAX_BEDS } from '@dashboard/showcase/autoDemoConstants';
import type { EquipmentPlacement, MapLayout } from '@viewer/parser/types';

/** Sort beds row-major (top→bottom, left→right) and map to `demo_b_01`…`demo_b_10`. */
export function mapDemoBedsToLayout(beds: EquipmentPlacement[]): Map<string, EquipmentPlacement> {
  const sorted = [...beds].sort((a, b) => a.tileY - b.tileY || a.tileX - b.tileX);
  const out = new Map<string, EquipmentPlacement>();
  for (let i = 0; i < Math.min(DEMO_MAX_BEDS, sorted.length); i++) {
    const slot = DEMO_BED_IDS[i];
    const bed = sorted[i];
    if (slot && bed) out.set(slot, bed);
  }
  return out;
}

/**
 * Keep only the 10 demo beds in the parsed layout so the 3D scene matches
 * the Dashboard bed grid. Bed `equipmentId` is renamed to `demo_b_XX`.
 */
export function layoutWithDemoBedsOnly(layout: MapLayout): MapLayout {
  const beds = layout.equipment.filter((e) => e.type === 'bed');
  const demoMap = mapDemoBedsToLayout(beds);
  const keepTiles = new Set(
    [...demoMap.values()].map((b) => `${b.tileX},${b.tileY}`)
  );

  const equipment: EquipmentPlacement[] = [];
  for (const piece of layout.equipment) {
    if (piece.type !== 'bed') {
      equipment.push(piece);
      continue;
    }
    const key = `${piece.tileX},${piece.tileY}`;
    if (!keepTiles.has(key)) continue;
    const demoId = [...demoMap.entries()].find(([, b]) => b.tileX === piece.tileX && b.tileY === piece.tileY)?.[0];
    equipment.push(demoId ? { ...piece, equipmentId: demoId } : piece);
  }

  return { ...layout, equipment };
}
