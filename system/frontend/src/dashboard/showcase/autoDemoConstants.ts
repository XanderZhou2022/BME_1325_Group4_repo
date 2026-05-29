/** Must match `DEMO_MAX_BEDS` in `system/backend/api/app/demo/service.py`. */
export const DEMO_MAX_BEDS = 10;
export const DEMO_MIN_ACTIVE_PATIENTS = 5;

export const DEMO_BED_IDS = Array.from({ length: DEMO_MAX_BEDS }, (_, i) => `demo_b_${String(i + 1).padStart(2, "0")}`);
