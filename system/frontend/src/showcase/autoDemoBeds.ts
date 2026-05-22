import { DEMO_BED_IDS } from "./autoDemoConstants";
import type { AdmissionBoardRow } from "./autoDemoTypes";

export type FixedBedSlot = {
  bed_id: string;
  occupied: boolean;
  row?: AdmissionBoardRow;
};

export function buildFixedBedSlots(boardRows: AdmissionBoardRow[]): FixedBedSlot[] {
  const byBed = new Map(boardRows.map((r) => [r.bed_id, r]));
  return DEMO_BED_IDS.map((bed_id) => {
    const row = byBed.get(bed_id);
    return { bed_id, occupied: Boolean(row), row };
  });
}
