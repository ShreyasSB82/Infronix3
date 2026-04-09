/**
 * cadViewerBridge.js  v4.0  — BIM Edition
 * ========================================
 * Converts Infranix2 JSON layout data → three-cad-viewer Shapes tree.
 * Optionally adds the Anti-Gravity BIM Core layer.
 *
 * NO Three.js import — uses the standalone earcut library (earcut.js)
 * loaded separately to avoid the "multiple Three.js instances" conflict.
 *
 * UMD global: window.CadViewer  (from three-cad-viewer.min.js)
 * Earcut global: window.earcut  (from earcut.js)
 */
import { generateAGCore, buildAGConfig } from '/static/js/3d/antiGravityGenerator.js?cacheBust=998877';
import { generateMEP } from '/static/js/3d/interiorMepGenerator.js';

// ── Constants ─────────────────────────────────────────────────────────────────
const FLOOR_H  = 3.2;    // metres per storey
const SLAB_H   = 0.3;    // thick distinct concrete floor slab
const ROOM_H   = FLOOR_H - SLAB_H - 0.08; // full height room extrusion

const ROOM_COLORS = {
  living:      '#B2A4B8', // Lavender
  kitchen:     '#D6C8C1', // Warm Beige
  bedroom:     '#B7C3B6', // Muted Sage
  bathroom:    '#859BA5', // Slate Blue
  study:       '#C4B7CB', // Light Purple
  circulation: '#A9B0B3', // Cool Gray
  utility:     '#C2D1C1', // Light Mint
  corner:      '#D5C1B6', // Warm Rose
  storage:     '#9BA4A8', // Steel Gray
};

const ZONE_COLORS = {
  building:   '#B2A4B8',
  greenery:   '#43a047', // Vivid Grass Green
  parking:    '#78909c',
  utility:    '#859BA5',
  road:       '#cfd8dc',
  amenity:    '#D6C8C1',
};

// ── Coordinate utilities ──────────────────────────────────────────────────────

function isGeo(ring) {
  const p = ring?.[0];
  if (!p) return false;
  return Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
}

function geoToMetres(p, cx, cy) {
  const latRad = cy * Math.PI / 180;
  return [(p[0] - cx) * 111320 * Math.cos(latRad), (p[1] - cy) * 111320];
}

function normRing(ring, cx, cy, geographic) {
  const pts = ring.map(p => geographic ? geoToMetres(p, cx, cy) : [p[0] - cx, p[1] - cy]);
  // Remove closing duplicate
  if (pts.length > 1) {
    const [f, l] = [pts[0], pts[pts.length - 1]];
    if (Math.abs(f[0] - l[0]) < 1e-9 && Math.abs(f[1] - l[1]) < 1e-9) pts.pop();
  }
  return pts;
}

function centroid(pts) {
  const n = pts.length || 1;
  return [pts.reduce((s,p) => s+p[0], 0)/n, pts.reduce((s,p) => s+p[1], 0)/n];
}

// ── Polygon area (signed) — positive = CCW ────────────────────────────────────
function polygonArea(pts) {
  let a = 0;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    a += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1]);
  }
  return a / 2;
}

// ── Earcut triangulation  ─────────────────────────────────────────────────────
// earcut(flatCoords, holeIndices, dim) → flat index array  [i0,i1,i2, i3,i4,i5, ...]
function triangulate2D(pts) {
  // Ensure CCW for correct normals
  const ring = polygonArea(pts) < 0 ? [...pts].reverse() : pts;
  const flat  = ring.flatMap(p => [p[0], p[1]]);
  const earc  = window.earcut || (typeof earcut !== 'undefined' ? earcut : null);
  if (!earc) {
    // Fallback: naive fan from centroid
    const tris = [];
    for (let i = 1; i < ring.length - 1; i++) tris.push(0, i, i + 1);
    return { ring, tris };
  }
  return { ring, tris: earc(flat, null, 2) };
}

// ── Build complete extruded Shapes leaf geometry ──────────────────────────────

function tessellateExtrusion(ring2d, height, yBase) {
  const { ring: pts, tris: tris2d } = triangulate2D(ring2d);
  const N = pts.length;
  if (N < 3 || tris2d.length < 3) return null;

  const vertices  = [];
  const normals   = [];
  const triangles = [];

  // Bottom ring at yBase (indices 0..N-1)
  for (const [x, z] of pts) { vertices.push(x, yBase,          z); normals.push(0, -1, 0); }
  // Top ring at yBase+height (indices N..2N-1)
  for (const [x, z] of pts) { vertices.push(x, yBase + height, z); normals.push(0,  1, 0); }

  // Bottom cap — reverse winding so face points down
  const botCount = tris2d.length / 3;
  for (let i = 0; i < tris2d.length; i += 3) triangles.push(tris2d[i+2], tris2d[i+1], tris2d[i]);
  // Top cap — standard winding
  const topCount = botCount;
  for (let i = 0; i < tris2d.length; i += 3) triangles.push(N+tris2d[i], N+tris2d[i+1], N+tris2d[i+2]);

  // Side quads — one per edge, with face-specific normals
  let sideStart = 2 * N;
  const sideCounts = [];

  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N;
    const [x0, z0] = pts[i], [x1, z1] = pts[j];
    const ex = x1 - x0, ez = z1 - z0;
    const len = Math.sqrt(ex*ex + ez*ez) || 1;
    const nx = ez / len, nz = -ex / len;   // outward normal

    vertices.push(x0, yBase,         z0); normals.push(nx, 0, nz);
    vertices.push(x1, yBase,         z1); normals.push(nx, 0, nz);
    vertices.push(x1, yBase+height,  z1); normals.push(nx, 0, nz);
    vertices.push(x0, yBase+height,  z0); normals.push(nx, 0, nz);

    triangles.push(sideStart, sideStart+1, sideStart+2);
    triangles.push(sideStart, sideStart+2, sideStart+3);
    sideStart += 4;
    sideCounts.push(2);
  }

  // Edge outline (bottom + top perimeters + verticals)
  const edges = [];
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N;
    const [x0,z0] = pts[i], [x1,z1] = pts[j];
    edges.push(x0, yBase,        z0, x1, yBase,        z1);
    edges.push(x0, yBase+height, z0, x1, yBase+height, z1);
    edges.push(x0, yBase,        z0, x0, yBase+height, z0);
  }
  const numEdges = 3 * N;

  // obj_vertices (unique ring vertices)
  const obj_vertices = [];
  for (const [x,z] of pts) obj_vertices.push(x, yBase, z);
  for (const [x,z] of pts) obj_vertices.push(x, yBase+height, z);

  return {
    vertices, normals, triangles,
    triangles_per_face: [botCount, topCount, ...sideCounts],
    face_types:          new Array(2 + N).fill(0),
    edges,
    edge_types:          new Array(numEdges).fill(0),
    segments_per_edge:   new Array(numEdges).fill(1),
    obj_vertices,
  };
}

// ── Shapes node builders ──────────────────────────────────────────────────────

function makeLeaf(id, name, ring2d, height, yBase, color, alpha = 1.0, renderback = false) {
  const shape = tessellateExtrusion(ring2d, height, yBase);
  if (!shape) return null;
  return {
    version: 3, id, name,
    type: 'shapes', subtype: 'solid',
    state: [1, 1],
    color, alpha, renderback,
    texture: null, accuracy: null, bb: null,
    loc: [[0,0,0],[0,0,0,1]],
    shape,
  };
}

function makeGroup(id, name, parts) {
  return { version: 3, id, name, loc: [[0,0,0],[0,0,0,1]], parts };
}

// ── Bounding box ──────────────────────────────────────────────────────────────

function emptyBB() { return {xmin:1e9,xmax:-1e9,ymin:1e9,ymax:-1e9,zmin:1e9,zmax:-1e9}; }

function expandBB(bb, x, y, z) {
  if (x<bb.xmin) bb.xmin=x; if (x>bb.xmax) bb.xmax=x;
  if (y<bb.ymin) bb.ymin=y; if (y>bb.ymax) bb.ymax=y;
  if (z<bb.zmin) bb.zmin=z; if (z>bb.zmax) bb.zmax=z;
}

function ringToBB(bb, ring, yBottom, yTop) {
  for (const [x,z] of ring) { expandBB(bb,x,yBottom,z); expandBB(bb,x,yTop,z); }
}

function fixBB(bb, fallback) {
  if (!isFinite(bb.xmin)) return fallback;
  return bb;
}

// ── Interior → Shapes ─────────────────────────────────────────────────────────

function buildInteriorShapes(interior) {
  const floors = interior?.floors || [];
  if (!floors.length) return null;

  // Find coordinate type from any room
  const samplePt = floors.flatMap(f => f.rooms?.map(r => r.coords?.[0]) || []).find(Boolean);
  const geographic = isGeo(samplePt ? [samplePt] : []);

  // Global centroid for recentering
  const allPts = floors.flatMap(f => [
    ...(f.boundary || []),
    ...(f.rooms || []).flatMap(r => r.coords || []),
  ]);
  const [cx, cy] = centroid(allPts);

  const totalH = floors.length * FLOOR_H;
  const bb     = emptyBB();
  const parts  = [];

  // Shell ring from floor 1 boundary
  let shellRing = null;
  const b0 = floors[0]?.boundary;
  if (b0?.length > 2) {
    shellRing = normRing(b0, cx, cy, geographic);
    ringToBB(bb, shellRing, 0, totalH);
  }

  // Building shell (transparent glass)
  if (shellRing?.length >= 3) {
    const shell = makeLeaf('/Building/Shell', '🏛 Shell', shellRing, totalH, 0,
                           '#4da6ff', 0.08, true);
    if (shell) parts.push(shell);
  }

  // Each floor
  for (const floor of floors) {
    const fn    = floor.floor || 1;
    const yBase = (fn - 1) * FLOOR_H;
    const flParts = [];

    // Floor slab
    const slabRing = shellRing
      || (floor.boundary?.length > 2 ? normRing(floor.boundary, cx, cy, geographic) : null);

    if (slabRing?.length >= 3) {
      // 1. Defined Thick Concrete Slab
      const slab = makeLeaf(`/Building/Floor${fn}/Slab`, `Floor ${fn} Slab`,
                            slabRing, SLAB_H, yBase, '#333333', 1.0);
      if (slab) { flParts.push(slab); ringToBB(bb, slabRing, yBase, yBase+SLAB_H); }

      // 2. Custom Layout-fitting Glass Shell Envelope
      const shell = makeLeaf(`/Building/Floor${fn}/Shell`, `Glass Facade ${fn}`,
                             slabRing, FLOOR_H, yBase, '#1e293b', 0.20);
      if (shell) { flParts.push(shell); ringToBB(bb, slabRing, yBase, yBase+FLOOR_H); }
    }

    // Open Floorplan Rooms
    (floor.rooms || []).forEach((room, ri) => {
      const coords = room.coords;
      if (!coords?.length || coords.length < 3) return;
      const ring  = normRing(coords, cx, cy, geographic);
      if (ring.length < 3) return;
      
      const color = ROOM_COLORS[(room.type||'').toLowerCase()] || room.color || '#B2A4B8';
      const rId = `/Building/Floor${fn}/${(room.type||'room').replace(/\W/g,'')}${ri}`;
      const roomParts = [];

      // Generate a distinct internal 5cm floor plate for the room
      const floorLeaf = makeLeaf(`${rId}_Floor`, `Internal Floor`, ring, 0.05, yBase+SLAB_H, color, 1.0);
      if (floorLeaf) roomParts.push(floorLeaf);

      if (roomParts.length > 0) {
        flParts.push(makeGroup(rId, room.name || `Room ${ri+1}`, roomParts));
        ringToBB(bb, ring, yBase+SLAB_H, yBase+FLOOR_H);
      }
    });

    parts.push(makeGroup(`/Building/Floor${fn}`, `📐 Floor ${fn}`, flParts));
  }

  return {
    version: 3, name: '🏢 Building', id: '/Building',
    loc: [[0,0,0],[0,0,0,1]], normal_len: 0,
    bb: fixBB(bb, {xmin:-10,xmax:10,ymin:0,ymax:totalH,zmin:-10,zmax:10}),
    parts,
  };
}

function makeTree(id, cx, cz, yBase) {
  const parts = [];
  const trunkRing = Array.from({length:8}, (_,i) => {
    const a = (i/8)*Math.PI*2; return [cx + 0.2*Math.cos(a), cz + 0.2*Math.sin(a)];
  });
  parts.push(makeLeaf(`${id}_trunk`, 'Trunk', trunkRing, 2.0, yBase, '#A19D94', 1.0));
  const canopy1 = Array.from({length:12}, (_,i) => {
    const a = (i/12)*Math.PI*2; return [cx + 1.8*Math.cos(a), cz + 1.8*Math.sin(a)];
  });
  parts.push(makeLeaf(`${id}_c1`, 'Canopy', canopy1, 1.2, yBase + 1.5, '#66bb6a', 0.95));
  const canopy2 = Array.from({length:12}, (_,i) => {
    const a = (i/12)*Math.PI*2; return [cx + 1.2*Math.cos(a), cz + 1.2*Math.sin(a)];
  });
  parts.push(makeLeaf(`${id}_c2`, 'Canopy Top', canopy2, 1.2, yBase + 2.5, '#4caf50', 0.95));
  return makeGroup(id, 'Tree Context', parts);
}

// ── Site plan → Shapes ────────────────────────────────────────────────────────

function buildSiteShapes(sitePlan, numFloors) {
  const features = sitePlan?.zones?.features || [];
  if (!features.length) return null;

  const allRings = [];
  for (const f of features) {
    const geom = f.geometry || {};
    if (geom.type === 'Polygon') allRings.push(...geom.coordinates);
    else if (geom.type === 'MultiPolygon') geom.coordinates.forEach(p => allRings.push(...p));
  }
  const geographic = isGeo(allRings[0] || []);
  const [cx, cy]   = centroid(allRings.flat());

  const bb = emptyBB();
  const siteParts = [];

  features.forEach((feat, fi) => {
    const props    = feat.properties || {};
    const zoneType = (props.zone || 'zone').toLowerCase();
    const nf       = Number(props.num_floors || numFloors || 3);
    const isBuilding = zoneType === 'building';
    let height = isBuilding ? Math.max(FLOOR_H, nf * FLOOR_H) : 0.02; // ultra flat land
    let yStart = isBuilding ? 0 : -0.02; // flush ground
    
    const color    = ZONE_COLORS[zoneType] || '#60b4ff';
    const alpha    = isBuilding ? 0.05 : 1.0;

    const geom = feat.geometry || {};
    const rawRings = geom.type === 'Polygon'      ? [geom.coordinates[0]]
                   : geom.type === 'MultiPolygon' ? geom.coordinates.map(p => p[0])
                   : [];

    rawRings.forEach((rawRing, ri) => {
      const ring = normRing(rawRing, cx, cy, geographic);
      if (ring.length < 3) return;
      const leaf = makeLeaf(`/Site/${zoneType}${fi}_${ri}`,
        `${zoneType.charAt(0).toUpperCase()+zoneType.slice(1)} ${fi+1}`,
        ring, height, yStart, color, alpha, isBuilding);
      if (leaf) { siteParts.push(leaf); ringToBB(bb, ring, yStart, yStart+height); }

      // Restored procedural diagrammatic trees requested by user
      if (zoneType === 'greenery' || zoneType === 'amenity') {
        const [bcx, bcz] = centroid(ring);
        const t = makeTree(`/Site/Tree_${fi}_${ri}`, bcx, bcz, 0);
        if (t) siteParts.push(t);
      }
    });
  });

  if (!siteParts.length) return null;
  return {
    version: 3, name: '🗺 Site Plan', id: '/Site',
    loc: [[0,0,0],[0,0,0,1]], normal_len: 0,
    bb: fixBB(bb, {xmin:-50,xmax:50,ymin:0,ymax:numFloors*FLOOR_H,zmin:-50,zmax:50}),
    parts: siteParts,
  };
}

// ── Merge all trees ───────────────────────────────────────────────────────────

function buildRootShapes(sitePlan, interior, agEnabled = false) {
  const building = interior?.floors?.length ? buildInteriorShapes(interior) : null;
  const site     = sitePlan?.zones?.features?.length
    ? buildSiteShapes(sitePlan, interior?.floors?.length || 3)
    : null;

  // Anti-Gravity BIM Core
  let agCore = null;
  if (agEnabled && (building || site)) {
    try {
      const agConfig = buildAGConfig(sitePlan, interior);
      agCore = generateAGCore(agConfig);
    } catch (e) {
      console.warn('[cadViewerBridge] AG core generation failed:', e);
    }
  }

  // Interior Structured MEP
  let mepShapes = null;
  if (interior?.floors?.length) {
    try {
      mepShapes = generateMEP(interior);
    } catch (e) {
      console.warn('[cadViewerBridge] MEP generation failed:', e);
    }
  }

  // Collect non-null nodes
  const nodes = [building, mepShapes, site, agCore].filter(Boolean);
  if (!nodes.length) return null;
  if (nodes.length === 1) return nodes[0];

  // Merge bounding boxes
  const bb = nodes.reduce((acc, n) => ({
    xmin: Math.min(acc.xmin, n.bb.xmin),
    xmax: Math.max(acc.xmax, n.bb.xmax),
    ymin: Math.min(acc.ymin, n.bb.ymin),
    ymax: Math.max(acc.ymax, n.bb.ymax),
    zmin: Math.min(acc.zmin, n.bb.zmin),
    zmax: Math.max(acc.zmax, n.bb.zmax),
  }), { xmin:1e9, xmax:-1e9, ymin:1e9, ymax:-1e9, zmin:1e9, zmax:-1e9 });

  return {
    version: 3, name: 'Infranix BIM Layout', id: '/Root',
    loc: [[0,0,0],[0,0,0,1]], normal_len: 0, bb,
    parts: nodes,
  };
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * initialiseCADViewer(container, sitePlan, interior, agEnabled?)
 * → mounts three-cad-viewer, returns { display, viewer } or null.
 */
export function initialiseCADViewer(container, sitePlan, interior, agEnabled = false) {
  const TCV = window.CadViewer;
  if (!TCV?.Display || !TCV?.Viewer) {
    console.error('[cadViewerBridge] window.CadViewer.Display or .Viewer not found — is three-cad-viewer.min.js loaded?');
    return null;
  }

  container.innerHTML = '';

  const W = container.clientWidth  || window.innerWidth;
  const H = container.clientHeight || (window.innerHeight - 54);

  const displayOptions = {
    cadWidth:        W,
    height:          H,
    treeWidth:       260,
    theme:           'dark',
    glass:           false,
    tools:           true,
    pinning:         false,
    measureTools:    false,
    explodeTool:     false,
    zebraTool:       false,
  };

  // ── Step 1: Create Display (DOM + toolbar only, no viewer yet) ────────────
  const display = new TCV.Display(container, displayOptions);

  // ── Step 2: Create Viewer (attaches to display, calls back display.setupUI) ──
  const viewer = new TCV.Viewer(display, displayOptions, () => {});

  const shapes = buildRootShapes(sitePlan, interior, agEnabled);
  if (!shapes) {
    console.warn('[cadViewerBridge] No geometry to render');
    return { display, viewer };
  }

  const bb   = shapes.bb;
  const cx   = (bb.xmin + bb.xmax) / 2;
  const cy   = (bb.ymin + bb.ymax) / 2;
  const cz   = (bb.zmin + bb.zmax) / 2;
  const diag = Math.max(bb.xmax-bb.xmin, bb.ymax-bb.ymin, bb.zmax-bb.zmin, 1);
  const dist = diag * 2.0;

  // ── Step 3: Render shapes ─────────────────────────────────────────────────
  try {
    viewer.render(
      shapes,
      {
        edgeColor:        0x1c2a3a,
        ambientIntensity: 1.0,
        directIntensity:  1.4,
        metalness:        0.05,
        roughness:        0.55,
        defaultOpacity:   0.7,
      },
      {
        axes:        false,
        axes0:       false,
        grid:        [false, true, false],
        ortho:       false,
        control:     'orbit',
        up:          'Y',
        transparent: false,
        blackEdges:  false,
        collapse:    1,
        zoom:        0.9,
        position:    [cx + dist*0.55, cy + dist*0.40, cz + dist*0.70],
        quaternion:  null,
      }
    );
    console.info('[cadViewerBridge] Render complete:', shapes.name);
  } catch (err) {
    console.error('[cadViewerBridge] viewer.render() error:', err);
  }

  return { display, viewer };
}

/**
 * exportDXF(sitePlan, interior, agEnabled?)
 * Triggers browser download of a layered BIM DXF file.
 * When agEnabled=true, includes all Anti-Gravity AIA layers.
 */
export async function exportDXF(sitePlan, interior, agEnabled = false) {
  const body = {};
  if (sitePlan) body.site_plan = sitePlan;
  if (interior) body.interior  = interior;
  if (!body.site_plan && !body.interior) throw new Error('Nothing to export');

  // Add AG config if enabled
  if (agEnabled) {
    body.anti_gravity = buildAGConfig(sitePlan, interior);
  }

  const res = await fetch('/api/export/dxf', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'DXF export failed');
  }
  const blob = await res.blob();
  const url  = URL.createObjectURL(blob);
  const filename = agEnabled ? 'infranix_bim_ag_export.dxf' : 'infranix_export.dxf';
  Object.assign(document.createElement('a'), { href: url, download: filename }).click();
  URL.revokeObjectURL(url);
}
