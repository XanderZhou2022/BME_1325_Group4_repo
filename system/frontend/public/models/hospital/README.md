# Hospital 3D models (FBX)

The 3D viewer loads FBX assets from this folder at runtime (`/models/hospital/*.fbx`).

Without these files the viewer still runs using **procedural fallbacks** (coloured floor tiles, wall boxes, equipment cubes). Copy the Kenney **Hospital** interior pack FBX exports here for full fidelity.

## Expected files

- `bed.fbx`, `chair.fbx`, `waiting_chair.fbx`, `computer.fbx`, `diagnostic_table.fbx`, `medical_equipment.fbx`, `wheelchair.fbx`
- `floor_reception.fbx`, `floor_office.fbx`, `floor_ward.fbx`, `wall_small_ward.fbx`
- `Texture_Atlas_Colors_2.png` (shared atlas)
- Reception decorations: `reception_desk.fbx`, `chair_reception.fbx`, `pc_monitor.fbx`, etc.

See `src/viewer/components/ThreeFloorPlan.tsx` for the full list of paths.
