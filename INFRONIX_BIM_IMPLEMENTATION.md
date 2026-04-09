# INFRONIX — Full BIM + UX Implementation Spec
## Anti-Gravity Edition · Bangalore Infrastructure Integration · CAD Realism Pipeline

---

## 0. Overview & Architecture

This document defines the complete implementation stack for Infronix — a web-based
urban planning tool that takes a user-selected polygon from a Bangalore geo map and
produces: 2D voxel plans → 3D extruded BIM → CAD-realistic DXF/IFC output →
interior room layout → PDF submission report.

It also specifies the **anti-gravity structural module** — a speculative engineering
layer that models levitation cores, void meshes, and magnetic bearing shafts as BIM
objects, exportable as IFC IfcBeam / IfcColumn entities with custom property sets.

---

## 1. Technology Stack

```
Frontend:          React 18 + TypeScript + Vite
3D Engine:         Three.js r155 + @react-three/fiber + @react-three/drei
CAD Export:        three-dxf-writer (DXF) + web-ifc (IFC 4.0)
Map Layer:         MapLibre GL JS + PMTiles (self-hosted Bangalore tiles)
Voxel Grid:        Custom TypeScript engine (GridEngine.ts)
BIM Objects:       Custom IFC property sets (Pset_AntiGravity, Pset_InfraOffset)
PDF Export:        react-pdf / @react-pdf/renderer
State:             Zustand
Backend API:       FastAPI (Python) — voxel generation, DEM query, compliance check
```

---

## 2. Bangalore Infrastructure Map (Stage 0)

### 2.1 Map Setup

```typescript
// src/map/BangaloreMap.tsx
import maplibregl from 'maplibre-gl';

const LAYERS = {
  drainage:    'https://tiles.infronix.in/bangalore/swd/{z}/{x}/{y}.pbf',
  waterSupply: 'https://tiles.infronix.in/bangalore/bwssb/{z}/{x}/{y}.pbf',
  sewage:      'https://tiles.infronix.in/bangalore/ugd/{z}/{x}/{y}.pbf',
  zoning:      'https://tiles.infronix.in/bangalore/zoning/{z}/{x}/{y}.pbf',
  dem:         'https://tiles.infronix.in/bangalore/dem/{z}/{x}/{y}.pbf',
};

// Layer render spec
export const LAYER_STYLES = {
  'swd-lines': {
    type: 'line',
    paint: { 'line-color': '#1D9E75', 'line-width': 1.5, 'line-opacity': 0.7 },
    filter: ['==', ['get', 'type'], 'stormwater'],
  },
  'bwssb-mains': {
    type: 'line',
    paint: { 'line-color': '#185FA5', 'line-width': 2.0, 'line-dasharray': [4, 2] },
  },
  'ugd-trunk': {
    type: 'line',
    paint: { 'line-color': '#BA7517', 'line-width': 1.5, 'line-dasharray': [2, 3] },
  },
  'zoning-residential': {
    type: 'fill',
    paint: { 'fill-color': '#7F77DD', 'fill-opacity': 0.12 },
    filter: ['==', ['get', 'zone'], 'R1'],
  },
  'zoning-commercial': {
    type: 'fill',
    paint: { 'fill-color': '#D85A30', 'fill-opacity': 0.10 },
    filter: ['in', ['get', 'zone'], ['literal', ['C1','C2','MU']]],
  },
};
```

### 2.2 Plot Selection with Infrastructure Clearance

```typescript
// src/map/PlotSelector.tsx
interface PlotClearanceCheck {
  drainageOffset: number;      // metres from nearest SWD line
  waterMainOffset: number;     // metres from BWSSB main
  sewageTrunkOffset: number;   // metres from UGD trunk
  floodZone: 'safe' | 'buffer' | 'restricted';
  zoningClass: 'R1' | 'R2' | 'C1' | 'C2' | 'MU' | 'restricted';
  isSelectable: boolean;       // only R1/R2 parcels outside flood buffer
}

// Called on map click — queries tile feature properties + DEM
export async function checkPlotClearance(
  lngLat: [number, number],
  polygonGeoJSON: GeoJSON.Polygon
): Promise<PlotClearanceCheck> {
  const res = await fetch('/api/clearance', {
    method: 'POST',
    body: JSON.stringify({ polygon: polygonGeoJSON, point: lngLat }),
  });
  return res.json();
}

// UI feedback on hover
// - Green outline: selectable residential
// - Orange outline: buffer zone (allow with warning)
// - Red fill: restricted / commercial / flood zone → not selectable
```

### 2.3 Infrastructure Data Sources (Bangalore)

| Layer         | Source                              | Update freq | Format    |
|---------------|-------------------------------------|-------------|-----------|
| Drainage SWD  | BBMP Open Data / GIS cell           | Annual      | GeoJSON   |
| Water mains   | BWSSB infrastructure GIS            | Biannual    | Shapefile |
| Sewage UGD    | BWSSB UGD project maps              | Biannual    | Shapefile |
| Zoning        | BMRDA Master Plan 2031              | Decadal     | PDF→GeoJSON|
| DEM terrain   | SRTM 30m + Cartosat-1 1m patches    | Static      | GeoTIFF   |
| Flood zones   | KSNDMC / BBMP flood risk maps       | Annual      | GeoJSON   |

---

## 3. Voxel Grid Engine (Stage 2)

```typescript
// src/engine/GridEngine.ts

export interface VoxelCell {
  x: number; y: number;          // grid indices
  type: 'building' | 'greenery' | 'parking' | 'utility' | 'empty';
  floor: number;
  infraFlag?: 'drainage_buffer' | 'water_offset' | 'sewage_offset';
}

export class GridEngine {
  private cells: Map<string, VoxelCell> = new Map();
  private cellSize = 2.5; // metres per cell

  /** Rasterise a GeoJSON polygon into voxel cells */
  rasterise(polygon: GeoJSON.Polygon, infraOffsets: InfraOffsets): VoxelCell[] {
    // 1. Compute bounding box in local coords
    // 2. Fill interior cells using point-in-polygon
    // 3. Mark buffer cells within infraOffsets distances
    // 4. Return sorted cell array
    return [];
  }

  /** Assign zone types respecting preferences and infra buffers */
  assignZones(
    cells: VoxelCell[],
    prefs: { building: number; greenery: number; parking: number; utility: number }
  ): VoxelCell[] {
    // Priority: utility near STP corner, parking near road facing,
    // greenery as perimeter ring, building fills remainder
    return cells;
  }
}

export interface InfraOffsets {
  drainageBuffer: number;   // e.g. 3 m no-build from SWD pipe
  waterMainBuffer: number;  // e.g. 1.5 m
  sewageBuffer: number;     // e.g. 2 m
}
```

---

## 4. CAD 3D BIM Engine (Stage 4)

### 4.1 Three.js Realistic Material System

Replace flat voxel boxes with **parametric BIM geometry** using realistic PBR materials.
Reference: Image 7 (transparent glass envelope + concrete slabs + MEP shafts).

```typescript
// src/bim/materials.ts
import * as THREE from 'three';

export const BIMMaterials = {
  concreteWall: new THREE.MeshStandardMaterial({
    color: 0xc8c2b8,
    roughness: 0.85,
    metalness: 0.02,
    // normalMap: concreteNormal (loaded via useTexture)
  }),

  glass: new THREE.MeshPhysicalMaterial({
    color: 0xa8d8ea,
    transmission: 0.88,
    roughness: 0.05,
    metalness: 0.1,
    ior: 1.45,
    thickness: 0.12,
    transparent: true,
    opacity: 0.35,
    side: THREE.DoubleSide,
  }),

  greenRoof: new THREE.MeshStandardMaterial({
    color: 0x4a7c59,
    roughness: 0.9,
    metalness: 0.0,
  }),

  asphalt: new THREE.MeshStandardMaterial({
    color: 0x3a3a3a,
    roughness: 0.95,
    metalness: 0.05,
  }),

  // Anti-gravity levitation core — metallic glowing ring
  levitationRing: new THREE.MeshStandardMaterial({
    color: 0x4fc3f7,
    emissive: 0x0288d1,
    emissiveIntensity: 0.6,
    metalness: 0.95,
    roughness: 0.1,
  }),

  // Anti-gravity void — semi-transparent suspension field
  gravityVoid: new THREE.MeshPhysicalMaterial({
    color: 0x7c4dff,
    transmission: 0.6,
    roughness: 0.0,
    metalness: 0.3,
    transparent: true,
    opacity: 0.25,
    wireframe: false,
  }),

  MEPPipe: new THREE.MeshStandardMaterial({
    color: 0x607d8b,
    roughness: 0.4,
    metalness: 0.7,
  }),

  waterPipe: new THREE.MeshStandardMaterial({
    color: 0x1565c0,
    roughness: 0.35,
    metalness: 0.8,
  }),

  sewagePipe: new THREE.MeshStandardMaterial({
    color: 0x6d4c41,
    roughness: 0.5,
    metalness: 0.4,
  }),
};
```

### 4.2 BIM Object Hierarchy

```typescript
// src/bim/BIMObjects.ts

export interface BIMBuilding {
  id: string;
  floors: BIMFloor[];
  shell: BIMShell;            // outer facade geometry
  mepShafts: MEPShaft[];
  antiGravityCore?: AntiGravityCore;
  infraConnections: InfraConnection[];
}

export interface BIMFloor {
  level: number;              // 0 = ground
  elevation: number;          // metres from site datum
  rooms: BIMRoom[];
  slab: THREE.BufferGeometry;
  structuralGrid: StructuralGrid;
}

export interface BIMShell {
  exteriorWalls: THREE.Mesh[];
  glazing: THREE.Mesh[];      // curtain wall panels
  parapet: THREE.Mesh;
  roof: THREE.Mesh;
}

export interface MEPShaft {
  type: 'electrical' | 'plumbing' | 'hvac' | 'fire';
  position: THREE.Vector3;
  radius: number;
  height: number;             // full building height
  mesh: THREE.Mesh;
}

// Anti-gravity structural specification
export interface AntiGravityCore {
  corePosition: THREE.Vector3;      // centroid of building footprint
  levitationRings: LevitationRing[];
  gravityVoidZone: GravityVoid;
  superconductingShaft: SCShaft;
  ifcPropertySet: Pset_AntiGravity;
}

export interface LevitationRing {
  elevation: number;           // height above ground
  outerRadius: number;
  innerRadius: number;
  material: 'HTS_YBCO' | 'NbTi' | 'MgB2';
  coolingType: 'LN2' | 'cryo_cooler' | 'passive_HTc';
  liftCapacity_kN: number;
  mesh: THREE.Mesh;
}

export interface GravityVoid {
  boundingBox: THREE.Box3;
  fieldStrength_T: number;     // Tesla (flux density)
  stableAltitude_m: number;    // design levitation height
  mesh: THREE.Mesh;
}

export interface SCShaft {
  // Central vertical shaft carrying power + cryo lines
  position: THREE.Vector3;
  diameter: number;            // metres
  cryolineDiameter: number;
  powerConduitDiameter: number;
  mesh: THREE.Mesh;
}

// IFC Custom Property Set for Anti-Gravity
export interface Pset_AntiGravity {
  LiftCapacity_kN: number;
  DesignAltitude_m: number;
  SuperconductorMaterial: string;
  OperatingTemperature_K: number;
  MagneticFluxDensity_T: number;
  CoolingSystemType: string;
  SafetyFactor: number;
  CertificationStandard: string;  // 'ISO/TS 24497' or project-specific
}
```

### 4.3 MEP + Infrastructure Connection Geometry

```typescript
// src/bim/InfraConnections.ts

export interface InfraConnection {
  type: 'water_supply' | 'drainage' | 'sewage' | 'power';
  entryPoint: THREE.Vector3;    // where pipe enters building boundary
  routingPath: THREE.Vector3[]; // waypoints through building
  pipeDiameter: number;         // mm
  material: string;
  ifcClass: 'IfcPipeSegment' | 'IfcCableCarrierSegment';
}

export function buildDrainageGeometry(connection: InfraConnection): THREE.TubeGeometry {
  const curve = new THREE.CatmullRomCurve3(connection.routingPath);
  return new THREE.TubeGeometry(curve, 24, connection.pipeDiameter / 2000, 8, false);
}

// Underground routing from SWD/BWSSB/UGD connection points
export function routeUndergroundInfra(
  buildingFootprint: THREE.Shape,
  siteInfra: {
    swdEntry: THREE.Vector2;        // nearest SWD manhole
    bwssbEntry: THREE.Vector2;      // nearest BWSSB connection
    ugdEntry: THREE.Vector2;        // nearest UGD manhole
  }
): InfraConnection[] {
  // Returns 3 InfraConnection objects with underground routing paths
  // Routing respects 1m minimum cover depth
  // Crossing paths get vertical offsets: water above sewage above drainage
  return [];
}
```

---

## 5. Anti-Gravity Structural Module — Detailed Spec

### 5.1 Design Intent

The anti-gravity core models a **high-temperature superconducting (HTS) magnetic
levitation system** integrated into the building's structural BIM. This is treated as
a **speculative engineering layer** — modelled as real IFC objects with custom
property sets, so they can be exported, reviewed, and coordinated in Revit/Archicad.

The system appears in the CAD 3D view as:
- **Transparent glass outer envelope** (as per Image 7)
- **Horizontal levitation rings** per floor (gold/amber cylindrical rings — Image 7)
- **Central superconducting shaft** (vertical gray column)
- **Suspension field void** (semi-transparent blue-purple volume)
- **Cryo-cooling lines** (blue piping helixing up the shaft, as per Image 7 spiral)

### 5.2 Geometry Generation

```typescript
// src/bim/AntiGravityGenerator.ts
import * as THREE from 'three';
import { BIMMaterials } from './materials';

export function generateAntiGravityCore(
  buildingBox: THREE.Box3,
  floors: number,
  floorHeight: number
): AntiGravityCore {
  const centroid = new THREE.Vector3();
  buildingBox.getCenter(centroid);

  // 1. Central superconducting shaft (gray cylinder)
  const shaftGeo = new THREE.CylinderGeometry(0.4, 0.4, floors * floorHeight, 32);
  const shaftMesh = new THREE.Mesh(shaftGeo, BIMMaterials.concreteWall);
  shaftMesh.position.set(centroid.x, floors * floorHeight / 2, centroid.z);

  // 2. Levitation rings — one per floor (gold/amber torus)
  const rings: LevitationRing[] = Array.from({ length: floors }, (_, i) => {
    const elev = (i + 0.5) * floorHeight;
    const ringGeo = new THREE.TorusGeometry(
      buildingBox.max.x - buildingBox.min.x > 20 ? 6 : 3,  // outer radius scales w/ building
      0.25, 16, 64
    );
    const ringMesh = new THREE.Mesh(ringGeo, BIMMaterials.levitationRing);
    ringMesh.rotation.x = Math.PI / 2;
    ringMesh.position.set(centroid.x, elev, centroid.z);

    return {
      elevation: elev,
      outerRadius: 6,
      innerRadius: 5.5,
      material: 'HTS_YBCO',
      coolingType: 'LN2',
      liftCapacity_kN: 240,
      mesh: ringMesh,
    };
  });

  // 3. Cryo-cooling helix (blue spiral around shaft — Image 7 reference)
  const helixPoints: THREE.Vector3[] = [];
  const turns = floors * 2;
  for (let t = 0; t <= turns * Math.PI * 2; t += 0.1) {
    helixPoints.push(new THREE.Vector3(
      centroid.x + 0.6 * Math.cos(t),
      (t / (turns * Math.PI * 2)) * floors * floorHeight,
      centroid.z + 0.6 * Math.sin(t)
    ));
  }
  const helixCurve = new THREE.CatmullRomCurve3(helixPoints);
  const helixGeo = new THREE.TubeGeometry(helixCurve, turns * 20, 0.06, 8, false);
  const helixMesh = new THREE.Mesh(helixGeo, BIMMaterials.waterPipe);

  // 4. Gravity void volume (semi-transparent bounding box)
  const voidGeo = new THREE.BoxGeometry(
    buildingBox.max.x - buildingBox.min.x - 2,
    floors * floorHeight,
    buildingBox.max.z - buildingBox.min.z - 2
  );
  const voidMesh = new THREE.Mesh(voidGeo, BIMMaterials.gravityVoid);
  voidMesh.position.set(centroid.x, floors * floorHeight / 2, centroid.z);

  // 5. Glass outer envelope
  const envelopeGeo = new THREE.BoxGeometry(
    buildingBox.max.x - buildingBox.min.x + 0.5,
    floors * floorHeight + 0.5,
    buildingBox.max.z - buildingBox.min.z + 0.5
  );
  const envelopeMesh = new THREE.Mesh(envelopeGeo, BIMMaterials.glass);
  envelopeMesh.position.set(centroid.x, floors * floorHeight / 2, centroid.z);

  return {
    corePosition: centroid,
    levitationRings: rings,
    gravityVoidZone: {
      boundingBox: buildingBox,
      fieldStrength_T: 12.5,
      stableAltitude_m: 0.8,
      mesh: voidMesh,
    },
    superconductingShaft: {
      position: centroid,
      diameter: 0.8,
      cryolineDiameter: 0.06,
      powerConduitDiameter: 0.04,
      mesh: shaftMesh,
    },
    ifcPropertySet: {
      LiftCapacity_kN: floors * 240,
      DesignAltitude_m: 0.8,
      SuperconductorMaterial: 'YBa₂Cu₃O₇₋ₓ (YBCO)',
      OperatingTemperature_K: 77,
      MagneticFluxDensity_T: 12.5,
      CoolingSystemType: 'Liquid Nitrogen LN₂ closed-loop',
      SafetyFactor: 3.0,
      CertificationStandard: 'IS 456:2000 + Infronix-AG-001',
    },
  };
}
```

---

## 6. IFC Export with Anti-Gravity Property Sets

```typescript
// src/export/IFCExporter.ts
import { IfcAPI } from 'web-ifc';

export async function exportIFC(building: BIMBuilding): Promise<Uint8Array> {
  const ifcApi = new IfcAPI();
  await ifcApi.Init();
  const model = ifcApi.CreateModel({ schema: 'IFC4' });

  // Standard BIM entities: IfcProject, IfcSite, IfcBuilding, IfcBuildingStorey
  // ...standard IFC boilerplate...

  // Custom property set for anti-gravity core
  if (building.antiGravityCore) {
    const ag = building.antiGravityCore.ifcPropertySet;
    const pset = ifcApi.CreateIfcEntity(model, IFCPROPERTYSET, {
      GlobalId: newGuid(),
      Name: { value: 'Pset_AntiGravity' },
      HasProperties: [
        makeRealProp(ifcApi, model, 'LiftCapacity_kN', ag.LiftCapacity_kN),
        makeRealProp(ifcApi, model, 'DesignAltitude_m', ag.DesignAltitude_m),
        makeTextProp(ifcApi, model, 'SuperconductorMaterial', ag.SuperconductorMaterial),
        makeRealProp(ifcApi, model, 'OperatingTemperature_K', ag.OperatingTemperature_K),
        makeRealProp(ifcApi, model, 'MagneticFluxDensity_T', ag.MagneticFluxDensity_T),
        makeTextProp(ifcApi, model, 'CoolingSystemType', ag.CoolingSystemType),
        makeRealProp(ifcApi, model, 'SafetyFactor', ag.SafetyFactor),
      ],
    });
    // Attach to IfcColumn (superconducting shaft)
    // ...
  }

  return ifcApi.ExportFileAsIFC(model);
}
```

---

## 7. DXF Export — CAD Realism

```typescript
// src/export/DXFExporter.ts
// Layers map to AIA CAD layer naming standard
export const DXF_LAYERS = {
  'A-WALL-EXTR':   { color: 7,  ltype: 'CONTINUOUS' },  // exterior walls
  'A-WALL-INTR':   { color: 8,  ltype: 'CONTINUOUS' },  // interior walls
  'A-GLAZ':        { color: 4,  ltype: 'CONTINUOUS' },  // glazing
  'A-ROOF':        { color: 6,  ltype: 'CONTINUOUS' },  // roof
  'S-COLS':        { color: 1,  ltype: 'CONTINUOUS' },  // structural columns
  'S-BEAMS':       { color: 2,  ltype: 'CONTINUOUS' },  // beams
  'M-PIPE-WATER':  { color: 5,  ltype: 'DASHED' },      // water supply
  'M-PIPE-SWR':    { color: 3,  ltype: 'DASHED2' },     // sewage
  'M-PIPE-SWD':    { color: 94, ltype: 'DASHDOT' },     // stormwater drainage
  'E-CONDUIT':     { color: 30, ltype: 'DOTTED' },      // electrical conduit
  'X-AGRAV-RINGS': { color: 40, ltype: 'CONTINUOUS' },  // anti-gravity rings
  'X-AGRAV-VOID':  { color: 4,  ltype: 'PHANTOM' },     // gravity void envelope
  'X-AGRAV-SHAFT': { color: 7,  ltype: 'CONTINUOUS' },  // SC shaft
  'SITE-INFRA':    { color: 94, ltype: 'DASHDOT2' },    // off-site infra connections
};
```

---

## 8. File Operations (create / delete / transform)

### Files to CREATE

```
src/
  map/
    BangaloreMap.tsx          # MapLibre map with infra layers
    PlotSelector.tsx          # click → polygon + clearance check
    LayerToggle.tsx           # UI to toggle drainage/water/sewage/zoning
    InfraLegend.tsx           # colour-coded legend for map layers

  engine/
    GridEngine.ts             # voxel rasteriser + zone assigner
    ComplianceEngine.ts       # FSI / setback / infra offset validator

  bim/
    BIMObjects.ts             # type definitions
    BIMBuilder.ts             # builds Three.js scene from BIM objects
    AntiGravityGenerator.ts   # generates AG core geometry
    InfraConnections.ts       # underground pipe routing
    materials.ts              # PBR material library
    RealisticRenderer.tsx     # Three.js scene with SSAO, HDR env map

  export/
    IFCExporter.ts            # IFC 4 with Pset_AntiGravity
    DXFExporter.ts            # AIA-layered DXF
    GLTFExporter.ts           # GLTF for web 3D viewer
    PDFReportGenerator.tsx    # react-pdf report (EN + TA)

  api/
    clearance.py              # POST /api/clearance — infra offset query
    voxel.py                  # POST /api/voxel — grid generation
    compliance.py             # POST /api/compliance — BBMP rules check
    dem.py                    # GET /api/dem — elevation query

public/
  tiles/bangalore/            # PMTiles for offline Bangalore infra layers
  hdri/
    construction_site.hdr     # HDR env map for realistic lighting
    overcast_sky.hdr
  textures/
    concrete_normal.jpg
    glass_roughness.jpg
    asphalt_diffuse.jpg
```

### Files to DELETE (stale flat-colour geometry)

```
src/
  viewer/
    VoxelMesh.tsx             # ← REPLACE with BIMBuilder.ts
    FlatColorMaterial.ts      # ← REPLACE with materials.ts PBR
    SimpleExtrude.ts          # ← REPLACE with RealisticRenderer.tsx
  planner/
    StaticColorZones.tsx      # ← REPLACE with LayerToggle.tsx + BangaloreMap.tsx
```

### Files to MODIFY

```
src/App.tsx                   # add Stage 0 map gate before Stage 1
src/viewer/CADViewer.tsx      # swap in RealisticRenderer, add AG toggle
src/planner/Planner.tsx       # add InfraOffsets panel, compliance banner
src/export/index.ts           # add IFC + GLTF alongside existing DXF
```

---

## 9. UX Flow — Screen-by-Screen

### Screen 0 — Bangalore Infrastructure Map

- Full-bleed MapLibre map centred on Bangalore (12.97°N, 77.59°E)
- Layer toggle panel (top-right): Drainage · Water Supply · Sewage · Zoning · Flood Risk
- Cursor: crosshair when hovering selectable residential parcels
- Click: draws polygon outline → runs `/api/clearance` → shows info card:
  - Plot area, ward, zoning class
  - Infrastructure distances (Drainage: 4.2 m ✓ · Water main: 2.1 m ✓ · Sewage trunk: 8.5 m ✓)
  - Flood zone: Safe / Buffer / Restricted (with KSNDMC citation)
- CTA: "Select this plot →" (disabled if restricted zone)

### Screen 1 — Plot Details (existing, enhanced)

- Show selected polygon on mini-map (top-left inset)
- Add: Infrastructure Offset panel showing derived no-build buffers overlaid on voxel grid
- Add: Compliance badge (BBMP FSI check — green ✓ / amber warning / red ✗)
- Retain: Building/Greenery/Parking/Utility sliders
- Add: Anti-Gravity toggle ("Enable AG structural core — speculative engineering layer")

### Screen 2 — 2D Voxel Plan (existing, enhanced)

- Overlay infrastructure buffer zones as hatched cells (cannot be assigned Building)
- Show sewage/water connection entry points as coloured markers on perimeter
- Voxel cells clickable → shows zone label + area
- AG toggle ON: show central void zone highlighted in the grid

### Screen 3 — Map 3D (existing, enhanced)

- Realistic PBR materials replacing flat colours
- Terrain mesh from DEM data (shows site slope)
- Underground infra connections visible as translucent pipes below grade

### Screen 4 — CAD 3D BIM (existing, enhanced)

- Glass envelope (Image 7 reference) wrapping the building mass
- Per-floor horizontal rings if AG enabled
- Central SC shaft visible through glass
- Cryo-cooling helix in blue
- MEP shafts visible as colour-coded cylinders (blue=water, brown=sewage, green=SWD, grey=electrical)
- Tree panel shows: Site Plan > Building 1 > [Shell, MEP Shafts, AG Core, Infra Connections]
- Export: DXF (all layers) · IFC 4 (with Pset_AntiGravity) · GLTF (for web)

### Screen 5 — Interior Layout (existing, enhanced)

- Room areas now show real m² (calculated from voxel cell count × cellSize²)
- AG core appears as a named zone: "Levitation Shaft — non-habitable"
- Utility zone includes: STP room, transformer room, cryo-cooling plant room

### Screen 6 — PDF Report (new)

- Cover page with plot location map (static image)
- Site data table (area, ward, zoning, road facing)
- Infrastructure compliance table
- Floor-wise room schedule
- AG system specification page (if enabled)
- BBMP submission checklist
- Export as PDF, direct download

---

## 10. Compliance Engine (BBMP Rules)

```python
# api/compliance.py

BBMP_RULES = {
    'R1': {
        'max_fsi': 1.75,
        'front_setback_m': 3.0,
        'side_setback_m': 1.5,
        'rear_setback_m': 1.5,
        'max_height_m': 15.0,    # G+3 = ~12.8m OK
        'parking_per_unit': 1,
    },
    'R2': {
        'max_fsi': 2.25,
        'front_setback_m': 4.0,
        'side_setback_m': 2.0,
        'rear_setback_m': 2.0,
        'max_height_m': 18.0,
    },
}

INFRA_BUFFERS = {
    'swd_major':    3.0,   # metres no-build from major SWD drain
    'swd_minor':    1.5,
    'bwssb_main':   1.5,
    'ugd_trunk':    2.0,
    'ugd_lateral':  1.0,
}

def check_compliance(polygon_geojson, prefs, zone, infra_offsets) -> ComplianceResult:
    area = compute_area(polygon_geojson)
    building_area = area * prefs['building'] / 100
    fsi = (building_area * prefs['floors']) / area
    rules = BBMP_RULES[zone]
    return ComplianceResult(
        fsi_ok=fsi <= rules['max_fsi'],
        setback_ok=check_setbacks(polygon_geojson, rules),
        height_ok=prefs['floors'] * 3.2 <= rules['max_height_m'],
        infra_ok=check_infra_buffers(polygon_geojson, infra_offsets),
        computed_fsi=round(fsi, 2),
        max_fsi=rules['max_fsi'],
    )
```

---

## 11. Anti-Gravity Prompt Block
### (Full specification prompt for LLM-assisted geometry generation)

```
SYSTEM: You are a structural BIM engineer specialising in speculative high-temperature
superconducting (HTS) magnetic levitation architecture. Generate IFC-compatible
geometry specifications and property sets for the following building.

Generate a complete AntiGravityCore specification for the following:

Building:
- Footprint: {polygon_wkt}
- Plot area: {area} m²
- Floors: {floors}
- Floor-to-floor height: 3.2 m
- Total building height: {floors * 3.2} m
- Road facing: {road_facing}
- Zoning: {zone}

Infrastructure offsets:
- Nearest BWSSB main: {water_offset} m
- Nearest SWD drain: {drainage_offset} m
- Nearest UGD trunk: {sewage_offset} m

Anti-gravity requirements:
1. Central superconducting shaft:
   - Location: centroid of building footprint
   - Diameter: 0.8 m (structural) + 0.12 m cladding
   - Material: reinforced concrete shell housing YBCO superconductor stack
   - Cryo-cooling: LN₂ closed-loop, -196°C / 77 K operating temperature
   - Cooling line: 60 mm dia helix at 0.6 m radius, 2 turns per floor

2. Levitation rings — one per floor at mid-slab elevation:
   - Geometry: torus, outer radius = min(6 m, footprint_inscribed_radius × 0.4)
   - Cross-section diameter: 250 mm
   - Material: YBCO bulk superconductor in stainless steel housing
   - Lift capacity per ring: 240 kN (design load)
   - Safety factor: 3.0 (per IS 456:2000 structural clause equivalent)

3. Gravity void zone:
   - Footprint: building outline minus 1.0 m perimeter strip
   - Height: full building height
   - Magnetic flux density: 12.5 T (design flux)
   - Stable levitation altitude: 0.8 m above structural floor

4. Glass outer envelope:
   - Type: unitised curtain wall
   - Vision glass: 10 mm outer + 16 mm argon cavity + 10 mm inner
   - Spandrel: opaque with metallic finish
   - Mullion spacing: 1.5 m horizontal, floor-to-floor vertical
   - Sill height: 900 mm from floor

5. MEP integration with anti-gravity:
   - All MEP shafts: minimum 2.0 m offset from SC shaft centre
   - Electrical conduit: EMF-shielded (mu-metal lining) within 3 m of shaft
   - Fire rating of shaft enclosure: 2 hours (IS 1641)
   - Cryo emergency vent: roof-level discharge at wind rose dominant direction

6. IFC export requirements:
   - SC shaft: IfcColumn with Pset_AntiGravity attached
   - Levitation rings: IfcBeam (toroidal) with Pset_AntiGravityRing
   - Void zone: IfcSpace type=INTERNAL, usage='AntiGravityVoid'
   - Cryo lines: IfcPipeSegment with Pset_Cryogenic
   - Glass envelope: IfcCurtainWall with Pset_CurtainWallCommon

7. DXF layer assignments:
   - SC shaft: X-AGRAV-SHAFT (colour 7, CONTINUOUS)
   - Levitation rings: X-AGRAV-RINGS (colour 40, CONTINUOUS)
   - Void zone: X-AGRAV-VOID (colour 4, PHANTOM)
   - Cryo helix: M-PIPE-CRYO (colour 5, DASHDOT)
   - Glass envelope: A-GLAZ (colour 4, CONTINUOUS)

8. Structural load assumptions:
   - Dead load: 4.5 kN/m² per floor (IS 875 Part 1)
   - Live load: 2.0 kN/m² residential (IS 875 Part 2)
   - AG lift contribution: 30% of dead load per floor (conservative)
   - Residual structural load on conventional columns: 70% of dead load
   - Wind load: Bangalore basic wind speed 33 m/s (IS 875 Part 3, Zone II)
   - Seismic zone: II (IS 1893) — horizontal AG damping coefficient 0.15

Output format: JSON matching AntiGravityCore TypeScript interface.
Include: corePosition, levitationRings[], gravityVoidZone, superconductingShaft, ifcPropertySet.
Also output: a plain-language structural narrative (max 200 words) in English.
```

---

## 12. Sewage + Water Supply Mapping Detail

### Underground infra visualisation layers (Three.js scene)

```typescript
// Underground pipes shown when "Infrastructure" toggle is ON in CAD 3D view

// Water supply (BWSSB) — blue tube, 1.0 m below grade
const waterEntry = new THREE.Mesh(
  new THREE.TubeGeometry(waterRouteCurve, 20, 0.05, 8, false),
  BIMMaterials.waterPipe
);
waterEntry.position.y = -1.0;  // below site datum

// Sewage (UGD) — brown tube, 1.5 m below grade (crosses below water)
const sewageEntry = new THREE.Mesh(
  new THREE.TubeGeometry(sewageRouteCurve, 20, 0.06, 8, false),
  BIMMaterials.sewagePipe
);
sewageEntry.position.y = -1.5;

// Stormwater drainage (SWD) — teal tube, 0.6 m below grade
const drainageEntry = new THREE.Mesh(
  new THREE.TubeGeometry(drainageRouteCurve, 20, 0.08, 8, false),
  BIMMaterials.MEPPipe  // teal-ish gray
);
drainageEntry.position.y = -0.6;

// Manholes as cylinders at connection points
const manholeGeo = new THREE.CylinderGeometry(0.3, 0.3, 0.1, 16);
```

### On-site infra routing (building interior)

```
Water supply route:
  BWSSB entry (perimeter) → basement overhead tank (5 000 L) →
  risers (per floor, 25 mm dia) → flat distribution (15 mm dia)

Sewage route:
  Floor drains → soil stacks (100 mm dia, 2 stacks) →
  underground collector (150 mm dia) → UGD manhole connection

Stormwater route:
  Roof (sloped to drain) → rainwater down-pipes (100 mm) →
  site percolation pits OR SWD connection (depending on BBMP consent)

STP (sewage treatment plant):
  Located in utility zone corner → treats greywater → recycled for
  flushing + landscaping (per BBMP mandatory STP > 20 flats)
```

---

## 13. Rendering Pipeline for CAD Realism

```typescript
// src/bim/RealisticRenderer.tsx
import { Canvas, useThree } from '@react-three/fiber';
import { Environment, SSAO, BakeShadows } from '@react-three/drei';
import { EffectComposer, SMAA } from '@react-three/postprocessing';

export function RealisticScene({ building }: { building: BIMBuilding }) {
  return (
    <Canvas shadows camera={{ position: [30, 25, 30], fov: 45 }}>
      {/* HDR environment lighting — construction site HDRI */}
      <Environment files="/hdri/overcast_sky.hdr" background={false} />

      {/* Ambient + directional (sun from south for Bangalore) */}
      <ambientLight intensity={0.4} />
      <directionalLight
        position={[20, 40, -10]}  // approx solar azimuth south-facing
        intensity={1.2}
        castShadow
        shadow-mapSize={[2048, 2048]}
      />

      {/* Post-processing for depth and realism */}
      <EffectComposer>
        <SSAO radius={0.4} intensity={20} luminanceInfluence={0.6} />
        <SMAA />
      </EffectComposer>

      {/* BIM geometry */}
      <BIMScene building={building} />

      {/* Ground plane with terrain mesh */}
      <TerrainMesh dem={building.siteDEM} />

      {/* Shadow receiver */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[500, 500]} />
        <shadowMaterial opacity={0.3} />
      </mesh>
    </Canvas>
  );
}
```

---

*End of INFRONIX BIM Implementation Spec — Anti-Gravity Edition*
*Generated: 2026-04-09 · Infronix · Chennai*
